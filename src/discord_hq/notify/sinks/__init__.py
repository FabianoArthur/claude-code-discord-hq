"""Where alerts go. Each sink exposes `notify(event, settings)`, never raises
and never prints (a webhook URL must never reach a log or stdout)."""
