"""Values imported from environment variables"""

import os


class Credentials:
    login: str
    password: str
    base_url: str
    is_sandbox: bool

    def __init__(self, env: str = "Test"):
        """Tastytrade credentials are read from OS environment variables which can be
        loaded from a `.env` file, exported in the shell, or directly set in the environment.

        TODO: Add support for loading credentials in a secure manner.

        Args:
            env (str, optional): Environment is either "Test" or "Live". Defaults to "Test".

        Raises:
            ValueError: If environment is not "Test" or "Live"
        """
        if env not in ["Test", "Live"]:
            raise ValueError("Environment must be either 'Test' or 'Live'")

        self.login: str = os.environ["TT_SANDBOX_USER"] if env == "Test" else os.environ["TT_USER"]

        self.password: str = (
            os.environ["TT_SANDBOX_PASS"] if env == "Test" else os.environ["TT_PASS"]
        )

        self.base_url: str = (
            os.environ["TT_SANDBOX_URL"] if env == "Test" else os.environ["TT_API_URL"]
        )

        self.is_sandbox: bool = True if env == "Test" else False
