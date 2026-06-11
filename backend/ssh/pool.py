from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .factory import SSHConnectionFactory
from .models import (
    ConnectionPurpose,
    ConnectionTarget,
    PoolBusyError,
    PooledSSHConnection,
    SSHAcquireTimeoutError,
    SSHConnectionError,
    SSHPoolConfig,
)


@dataclass
class _Bucket:
    connections: list[PooledSSHConnection] = field(default_factory=list)
    config: SSHPoolConfig | None = None
    _core_count: int = 0

    @property
    def live_count(self) -> int:
        return len(self.connections)


class SSHConnectionPool:
    """Thread-safe SSH connection pool.

    One pool per process.  Connections are grouped by target_key (hash of
    alias + hostname + port + username + auth identity + jump host).

    Usage::

        pool = SSHConnectionPool()
        conn = pool.acquire(target, purpose="exec")
        try:
            # use conn.client.exec_command(...)
        finally:
            pool.release(conn)
    """

    def __init__(
        self,
        config: SSHPoolConfig | None = None,
        factory: SSHConnectionFactory | None = None,
        cleanup_interval: int | None = None,
    ) -> None:
        self._config = config or SSHPoolConfig()
        self._factory = factory or SSHConnectionFactory(
            connect_timeout_seconds=self._config.connect_timeout_seconds,
            keepalive_seconds=self._config.keepalive_seconds,
        )
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._running = True
        interval = cleanup_interval or self._config.cleanup_interval_seconds
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, args=(interval,), daemon=True
        )
        self._cleanup_thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        target: ConnectionTarget,
        purpose: ConnectionPurpose = "exec",
        timeout: float | None = None,
    ) -> PooledSSHConnection:
        key = target.target_key()
        if timeout is None:
            timeout = self._config.acquire_timeout_seconds
        deadline = time.monotonic() + timeout

        with self._condition:
            bucket = self._get_or_create_bucket(key, target)
            while True:
                self._remove_dead(bucket)

                if purpose == "interactive":
                    conn = self._try_create_connection(bucket, target, key, purpose)
                    if conn is not None:
                        return conn
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SSHAcquireTimeoutError(
                            f"No available connection for {target.alias} within {timeout}s"
                        )
                    self._condition.wait(remaining)
                    continue

                conn = self._find_available(bucket, purpose)
                if conn is not None:
                    self._mark_acquired(conn, purpose)
                    return conn

                conn = self._try_create_connection(bucket, target, key, purpose)
                if conn is not None:
                    return conn

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SSHAcquireTimeoutError(
                        f"No available connection for {target.alias} within {timeout}s"
                    )
                self._condition.wait(remaining)

    def release(self, conn: PooledSSHConnection) -> None:
        key = conn.target_key
        with self._condition:
            bucket = self._buckets.get(key)
            conn.in_flight = max(0, conn.in_flight - 1)
            conn.last_used_at = time.monotonic()
            if conn.in_flight == 0:
                conn.purpose = None

            if not self._is_alive(conn):
                self._close_conn(conn)
                if bucket is not None and conn in bucket.connections:
                    bucket.connections.remove(conn)
                    if conn.is_core:
                        bucket._core_count = max(0, bucket._core_count - 1)

            if bucket is not None:
                self._condition.notify_all()

    def close_idle(self) -> int:
        """Close non-core idle connections. Returns count of closed connections."""
        now = time.monotonic()
        closed = 0
        with self._condition:
            for bucket in self._buckets.values():
                idle_conns = [
                    c
                    for c in bucket.connections
                    if not c.is_core
                    and not c.is_dedicated
                    and c.in_flight == 0
                    and (now - c.last_used_at) > bucket.config.idle_timeout_seconds
                ]
                for c in idle_conns:
                    self._close_conn(c)
                    bucket.connections.remove(c)
                    closed += 1
            if closed:
                self._condition.notify_all()
        return closed

    def stats(self) -> dict[str, Any]:
        with self._condition:
            targets = []
            total_live = 0
            total_in_flight = 0
            for key, bucket in self._buckets.items():
                alias = bucket.connections[0].target.alias if bucket.connections else key
                targets.append(
                    {
                        "alias": alias,
                        "target_key": key,
                        "live_connections": bucket.live_count,
                        "core_connections": bucket._core_count,
                        "in_flight": sum(c.in_flight for c in bucket.connections),
                        "max_connections": bucket.config.max_connections_per_target,
                        "max_channels_per_connection": bucket.config.max_channels_per_connection,
                        "idle_timeout_seconds": bucket.config.idle_timeout_seconds,
                    }
                )
                total_live += bucket.live_count
                total_in_flight += sum(c.in_flight for c in bucket.connections)
            return {
                "targets": targets,
                "total_live": total_live,
                "total_in_flight": total_in_flight,
            }

    def health(self, alias: str) -> dict[str, Any]:
        with self._condition:
            for bucket in self._buckets.values():
                for c in bucket.connections:
                    if c.target and c.target.alias == alias:
                        return {
                            "alias": alias,
                            "connection_id": c.id,
                            "is_alive": self._is_alive(c),
                            "in_flight": c.in_flight,
                            "is_core": c.is_core,
                            "is_dedicated": c.is_dedicated,
                            "age_seconds": round(time.monotonic() - c.created_at, 1),
                            "idle_seconds": round(time.monotonic() - c.last_used_at, 1),
                        }
        return {"alias": alias, "connection_id": None, "is_alive": False}

    def close_connection(self, alias: str) -> bool:
        with self._condition:
            for bucket in list(self._buckets.values()):
                for c in list(bucket.connections):
                    if c.target and c.target.alias == alias and c.in_flight == 0:
                        self._close_conn(c)
                        bucket.connections.remove(c)
                        if c.is_core:
                            bucket._core_count = max(0, bucket._core_count - 1)
                        self._condition.notify_all()
                        return True
        return False

    def shutdown(self) -> None:
        self._running = False
        with self._condition:
            for bucket in self._buckets.values():
                for c in list(bucket.connections):
                    self._close_conn(c)
                bucket.connections.clear()
            self._buckets.clear()
            self._condition.notify_all()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_bucket(self, key: str, target: ConnectionTarget) -> _Bucket:
        if key not in self._buckets:
            bucket = _Bucket(config=SSHPoolConfig(
                core_connections_per_target=self._config.core_connections_per_target,
                max_connections_per_target=self._config.max_connections_per_target,
                max_channels_per_connection=self._config.max_channels_per_connection,
                idle_timeout_seconds=self._config.idle_timeout_seconds,
                keepalive_seconds=self._config.keepalive_seconds,
                acquire_timeout_seconds=self._config.acquire_timeout_seconds,
                connect_timeout_seconds=self._config.connect_timeout_seconds,
                command_timeout_seconds=self._config.command_timeout_seconds,
                cleanup_interval_seconds=self._config.cleanup_interval_seconds,
                warmup_on_start=self._config.warmup_on_start,
            ))
            self._buckets[key] = bucket
        return self._buckets[key]

    def _remove_dead(self, bucket: _Bucket) -> None:
        for c in list(bucket.connections):
            if not self._is_alive(c):
                self._close_conn(c)
                bucket.connections.remove(c)
                if c.is_core:
                    bucket._core_count = max(0, bucket._core_count - 1)

    def _find_available(
        self, bucket: _Bucket, purpose: ConnectionPurpose
    ) -> PooledSSHConnection | None:
        candidates = [
            c
            for c in bucket.connections
            if self._is_alive(c)
            and not c.is_dedicated
            and c.in_flight < bucket.config.max_channels_per_connection
        ]
        if not candidates:
            return None

        if purpose == "long_running":
            idle = [c for c in candidates if c.in_flight == 0]
            return idle[0] if idle else None

        normal = [c for c in candidates if c.purpose != "long_running"]
        if normal:
            return min(normal, key=lambda c: c.in_flight)
        return None

    def _try_create_connection(
        self,
        bucket: _Bucket,
        target: ConnectionTarget,
        key: str,
        purpose: ConnectionPurpose,
    ) -> PooledSSHConnection | None:
        if (
            purpose == "interactive"
            and bucket.live_count >= bucket.config.max_connections_per_target
        ):
            self._evict_idle_shared_connection(bucket)

        if bucket.live_count >= bucket.config.max_connections_per_target:
            return None

        is_core = (
            purpose != "interactive"
            and bucket._core_count < bucket.config.core_connections_per_target
        )
        conn = self._create_pooled(target, key, is_core=is_core)
        if conn.is_core:
            bucket._core_count += 1
        if purpose == "interactive":
            conn.is_dedicated = True
        self._mark_acquired(conn, purpose)
        bucket.connections.append(conn)
        return conn

    def _evict_idle_shared_connection(self, bucket: _Bucket) -> None:
        candidates = [
            c
            for c in bucket.connections
            if c.in_flight == 0 and not c.is_dedicated
        ]
        if not candidates:
            return

        non_core = [c for c in candidates if not c.is_core]
        conn = non_core[0] if non_core else candidates[0]
        self._close_conn(conn)
        bucket.connections.remove(conn)
        if conn.is_core:
            bucket._core_count = max(0, bucket._core_count - 1)

    @staticmethod
    def _mark_acquired(conn: PooledSSHConnection, purpose: ConnectionPurpose) -> None:
        conn.in_flight += 1
        conn.purpose = purpose
        conn.last_used_at = time.monotonic()

    def _create_pooled(
        self, target: ConnectionTarget, key: str, is_core: bool
    ) -> PooledSSHConnection:
        now = time.monotonic()
        try:
            if hasattr(self._factory, "create_bundle"):
                client, aux_clients = self._factory.create_bundle(target)
            else:
                client = self._factory.create(target)
                aux_clients = getattr(client, "_adremote_aux_clients", [])
        except SSHConnectionError:
            raise
        except Exception as exc:
            raise SSHConnectionError(
                f"Failed to create SSH connection to {target.hostname}:{target.port}: {exc}"
            ) from exc

        return PooledSSHConnection(
            target_key=key,
            target=target,
            client=client,
            aux_clients=aux_clients,
            created_at=now,
            last_used_at=now,
            is_core=is_core,
        )

    @staticmethod
    def _is_alive(conn: PooledSSHConnection) -> bool:
        if conn.client is None:
            return False
        try:
            transport = conn.client.get_transport()
            return transport is not None and transport.is_active()
        except Exception:
            return False

    @staticmethod
    def _close_conn(conn: PooledSSHConnection) -> None:
        try:
            if conn.client is not None:
                conn.client.close()
        except Exception:
            pass
        for client in conn.aux_clients:
            try:
                client.close()
            except Exception:
                pass

    def _cleanup_loop(self, interval: int) -> None:
        while self._running:
            try:
                self.close_idle()
            except Exception:
                pass
            time.sleep(interval)
