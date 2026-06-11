# SSH Config Editor API

Run from the repository root:

```bash
.venv/bin/python -m backend.main
```

The API reads and writes `ssh_config` in the repository root. It uses the Python
standard library for HTTP; `paramiko` is only required for `POST
/api/ssh-configs/test`.
