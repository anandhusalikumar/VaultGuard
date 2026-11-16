# VaultGuard – Personal Cybersecurity Toolkit

A four-page desktop application built with Python and Tkinter. It provides local password-strength analysis and generation, file encryption/decryption, and heuristic URL scanning.

## Features

1. **Home** – Overview of activity statistics, recent history, and security tips.
2. **Password Lab** – Live password-strength estimate and secure password generator.
3. **File Vault** – Encrypt files and decrypt them using Fernet (`cryptography`).
4. **Link Scanner** – Offline URL heuristics with a risk score and findings.

## Requirements

- Python 3.9 or newer
- Tkinter (usually included with Python; on Debian/Ubuntu install `python3-tk` if needed)
- Dependencies listed in `requirements.txt`

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

## Important security notes

- The app creates `vaultguard.db` locally to store activity history. The database is intentionally excluded from version control.
- File encryption creates an `.enc` file and a separate `.key` file. Keep the key secure and separate; without it, the encrypted file cannot be recovered.
- Do not commit real `.key` files, encrypted personal files, passwords, or private data.
- Passwords entered into the strength tester are analysed locally; the app stores only the test result, not the password itself.
- URL checks are heuristic and educational. A low score is not proof that a website is safe; the scanner does not contact the website.

## Project files

```text
VaultGuard/
├── main.py
├── requirements.txt
├── README.md
└── .gitignore
```
