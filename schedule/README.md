Optional independent host setup; the ChatGPT replacement does not need these files.

Linux: put the extracted project at `$HOME/pm-career-scraper`, create its virtual environment and install requirements, copy the service and timer into `$HOME/.config/systemd/user/`, then run `systemctl --user daemon-reload` and `systemctl --user enable --now pm-careers.timer`. Check `journalctl --user -u pm-careers.service` and `output/latest/source-health.json`. Exit 2 means partial coverage even though systemd accepts the run as completed. Timers use Europe/Lisbon daylight-saving rules.

Windows: create a Task Scheduler task with a daily 08:00 trigger in the machine's Lisbon local timezone. Program: the full path to `.venv\Scripts\python.exe`; arguments: `run.py run --state data\state.sqlite3 --output output\latest`; Start in: the extracted project folder. Set "Do not start a new instance". Do not store a password in a script. These settings retrieve files only; they do not send email.

A local schedule requires an available host and persistent disk. Configure only one daily scheduler unless duplicate retrieval is intentional.
