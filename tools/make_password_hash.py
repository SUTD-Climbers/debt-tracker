import argparse
import getpass
from pathlib import Path
import re
import sys
import bcrypt


def hash_password(plain_password: str) -> str:
    # generate salt and bcrypt hash
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def save_user_to_secrets(username: str, hashed_pw: str) -> Path:
    # save user credentials directly into .streamlit/secrets.toml
    secrets_dir = Path(".streamlit")
    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_file = secrets_dir / "secrets.toml"

    if secrets_file.exists():
        with open(secrets_file, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        # initialize from example if available
        example_file = secrets_dir / "secrets.toml.example"
        if example_file.exists():
            with open(example_file, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = 'backend = "local_csv"\nprice_per_pass = 16.0\n\n[auth]\n[auth.users]\n'

    # ensure [auth.users] section exists
    if "[auth.users]" not in content:
        if "[auth]" in content:
            content = content.replace("[auth]", "[auth]\n[auth.users]")
        else:
            content += "\n[auth]\n[auth.users]\n"

    # check if user already exists
    user_line = f'{username} = "{hashed_pw}"'
    pattern = rf'^{re.escape(username)}\s*=.*$'
    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, user_line, content, flags=re.MULTILINE)
    else:
        # insert under [auth.users]
        parts = content.split("[auth.users]")
        new_content = parts[0] + f"[auth.users]\n{user_line}\n" + parts[1].lstrip("\n")

    with open(secrets_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    return secrets_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Create exco user account with secure bcrypt password hash.")
    parser.add_argument("--username", "-u", help="Username for login (e.g. exco_admin)")
    parser.add_argument("--password", "-p", help="Password for login")
    parser.add_argument("--save", action="store_true", help="Automatically save to .streamlit/secrets.toml")

    args = parser.parse_args()

    # get username
    username = args.username
    if not username:
        try:
            username = input("Enter username: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

    if not username:
        print("Error: Username cannot be empty.")
        sys.exit(1)

    # get password
    password = args.password
    if not password:
        try:
            password = getpass.getpass("Enter password: ")
            confirm = getpass.getpass("Confirm password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)

        if password != confirm:
            print("Error: Passwords do not match.")
            sys.exit(1)

    if not password:
        print("Error: Password cannot be empty.")
        sys.exit(1)

    # compute hash
    hashed = hash_password(password)

    print("\n" + "=" * 50)
    print("ACCOUNT CREDENTIALS GENERATED")
    print("=" * 50)
    print(f"Username : {username}")
    print(f"Hash     : {hashed}")
    print("=" * 50)

    # prompt to save to secrets if not specified via flag
    should_save = args.save
    if not should_save and not args.username:
        try:
            ans = input("\nDo you want to save this user to .streamlit/secrets.toml now? (y/n) [y]: ").strip().lower()
            should_save = ans in ("", "y", "yes")
        except (KeyboardInterrupt, EOFError):
            should_save = False

    if should_save:
        secrets_path = save_user_to_secrets(username, hashed)
        print(f"\nUser '{username}' has been saved to: {secrets_path}")
        print("You can now run Streamlit and log in immediately!")
    else:
        print("\nTo add this user manually, paste this into .streamlit/secrets.toml:")
        print(f'[auth.users]\n{username} = "{hashed}"')

    print("\nFor Streamlit Cloud deployment:")
    print("Paste this line into your Streamlit Cloud app settings under Secrets:")
    print(f'{username} = "{hashed}"')


if __name__ == "__main__":
    main()
