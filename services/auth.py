from pathlib import Path
from typing import Any, Dict, Optional
import bcrypt
import streamlit as st
import tomllib


def get_auth_users() -> Dict[str, str]:
    # load auth users from local secrets file or st.secrets
    local_secrets = Path(".streamlit") / "secrets.toml"
    if local_secrets.exists():
        try:
            with open(local_secrets, "rb") as f:
                data = tomllib.load(f)
                users = data.get("auth", {}).get("users", {})
                if users:
                    return {str(k): str(v) for k, v in users.items()}
        except Exception:
            pass

    # fallback to st.secrets for streamlit cloud deployments
    try:
        users = st.secrets.get("auth", {}).get("users", {})
        return {str(k): str(v) for k, v in users.items()}
    except Exception:
        return {}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # verify plain text password against bcrypt hash
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def authenticate_user(username: str, password: str) -> bool:
    # authenticate exco username and password against configured secrets
    if not username or not password:
        return False

    users = get_auth_users()
    if username in users:
        stored_hash = str(users[username])
        return verify_password(password, stored_hash)

    return False
