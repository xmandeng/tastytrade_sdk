from tastytrade.config import ConfigurationManager


class Credentials:
    login: str
    password: str
    base_url: str
    is_sandbox: bool

    @property
    def as_dict(self) -> dict:
        return vars(self)

    def __init__(self, config: ConfigurationManager, env: str = "Test"):
        """Tastytrade credentials are read from OS environment variables which can be loaded from a `.env` file, exported in the shell, or directly set in the environment.

        Args:
            env (str, optional): Environment is either "Test" or "Live". Defaults to "Test".

        Raises
            ValueError: If environment is not "Test" or "Live"
        """
        if env not in ["Test", "Live"]:
            raise ValueError("Environment must be either 'Test' or 'Live'")

        self.login: str = (
            config.get("TT_SANDBOX_USER") if env == "Test" else config.get("TT_USER")
        )
        # self.login: str = os.environ["TT_SANDBOX_USER"] if env == "Test" else os.environ["TT_USER"]

        self.password: str = (
            config.get("TT_SANDBOX_PASS") if env == "Test" else config.get("TT_PASS")
            # os.environ["TT_SANDBOX_PASS"] if env == "Test" else os.environ["TT_PASS"]
        )

        self.base_url: str = (
            config.get("TT_SANDBOX_URL") if env == "Test" else config.get("TT_API_URL")
        )

        self.account_number: str = (
            config.get("TT_SANDBOX_ACCOUNT")
            if env == "Test"
            else config.get("TT_ACCOUNT")
        )

        self.remember_me: bool = True

        self.is_sandbox: bool = True if env == "Test" else False


class InfluxCredentials:
    url: str
    token: str
    org: str

    def __init__(self, config: ConfigurationManager):
        self.url = config.get("INFLUX_DB_URL")
        self.org = config.get("INFLUX_DB_ORG")
        self.token = config.get("INFLUX_DB_TOKEN")
