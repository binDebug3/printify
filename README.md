# Printify to Etsy Auto Publisher

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Printify API](https://img.shields.io/badge/Printify-API-1DBA5A)](https://developers.printify.com/)
[![Gmail API](https://img.shields.io/badge/Google-Gmail%20API-EA4335?logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)

Automate scheduled product publishing from [Printify](https://printify.com/) to Etsy, with action logging and optional email notifications.

This project reads a daily publishing schedule, publishes eligible products through the Printify API, updates publish status in CSV, and sends a success email when an item goes live.

## Table Of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Configuration](#configuration)
- [Installation](#installation)
- [Usage](#usage)
- [Notifications](#notifications)
- [Contributing](#contributing)
- [License](#license)

## Features

- Scheduled publish flow using `data/schedule.csv`
- Printify publishing via REST API
- Product status write-back to schedule file (`publish_status`)
- File-based action logging to `meta/actions.log`
- Gmail notification on successful publish

## Project Structure

This repository expects the following workspace layout:

```text
data/
    schedule.csv
meta/
    api_token.txt
    shop_id.txt
    email_address.txt
    credentials.json
    mail_token.pickle
    actions.log
printify/
    publish.py
    tools.py
    notification.py
    logger_config.py
    README.md
    LICENSE
```

## Requirements

- Python `3.10+` (recommended)
- A Printify account with API access
- A connected Etsy sales channel in Printify
- Gmail API credentials (for notifications)

Python packages used by this project:

- `requests`
- `pandas`
- `google-auth`
- `google-auth-oauthlib`
- `google-api-python-client`

You can install them withthe requirements.yml file or directly via pip:

```bash
pip install requests pandas google-auth google-auth-oauthlib google-api-python-client
```

## Configuration

All runtime files are loaded from paths relative to `printify/`.

1. Follow these [instructions](https://developers.printify.com/#create-a-personal-access-token) 
    under `Create a personal access token` to set Printify API token
	 Put your token in `../meta/api_token.txt`.

2. Set default shop id
	 Put your shop id in `../meta/shop_id.txt`.

3. Configure publishing schedule. You can use `python tools.py` to obtain all product ids
    for the products in your shop
	 Create/update `../data/schedule.csv` with at least these columns:
	 - `publish_date` (format: `MM/DD/YYYY`)
	 - `shop_id`
	 - `product_id`
	 - `nick_name`
	 - `publish_status` (`True` or `False`)

4. Follow these [instructions](https://developers.google.com/workspace/guides/create-credentials) 
    to configure email notifications (optional)
	 - Put recipient email in `../meta/email_address.txt`
	 - Put OAuth client file in `../meta/cal_credentials.json`
	 - First run will create/update `../meta/mail_token.pickle`

5. Set scheduled task to run `python publish.py` daily (e.g. using cron or Windows Task Scheduler). 
    On Windows,
     - Open Task Scheduler using the Start menu
     - Click "Create Basic Task" on the right and add any name and description
     - Choose "Daily" and set your desired time
     - Choose the time of day to run the task (e.g. 9:00 AM)
     - Choose "Start a program" and browse to your Python executable (e.g. `C:\path\to\python.exe`)
        in your newly created virtual environment
     - Add the argument `publish.py` (no quotes or any special characters) 
     - Set the "Start in" field to the `printify/` directory (e.g. `C:\path\to\printify`)
     - Click "Finish" to create the task
     - Test the task by right-clicking it and selecting "Run"
     - A Command Prompt window should open and run the script, 
        and you can check the log file for results

## Installation

From the workspace root (`automation/`):

```bash
cd printify
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows PowerShell
pip install requests pandas google-auth google-auth-oauthlib google-api-python-client
```

## Usage

Run a single publishing job:

```bash
cd printify
python publish.py
```

What happens during a run:

1. Load token and schedule file
2. Filter rows for today's `publish_date`
3. Skip rows already marked `publish_status=True`
4. Publish remaining products via Printify API
5. Mark successful publishes as `True`
6. Send success email (if notification config is present)
7. Save updated schedule CSV


## Notifications

Email notifications are handled in `notification.py` using the Gmail API.

If token refresh or auth fails:

- remove `../meta/mail_token.pickle`
- rerun `python publish.py` to reauthorize

## Contributors

Dallin Stewart - dallinpstewart@gmail.com

[![LinkedIn][linkedin-icon]][linkedin-url1] [![GitHub][github-icon]][github-url1] [![Email][email-icon]][email-url1]


## License

Licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE).


[linkedIn-icon]: https://img.shields.io/badge/LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white
[linkedIn-url1]: https://www.linkedin.com/in/dallinstewart/

[github-icon]: https://img.shields.io/badge/GitHub-100000?style=for-the-badge&logo=github&logoColor=white
[github-url1]: https://github.com/binDebug3

[Email-icon]: https://img.shields.io/badge/Email-D14836?style=for-the-badge&logo=gmail&logoColor=white
[Email-url1]: mailto:dallinpstewart@gmail.com