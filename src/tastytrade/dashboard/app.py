import logging
import sys

if __name__ == "__main__":
    from tastytrade.common.logging import setup_logging
    from tastytrade.dashboard.dashboard import DashApp

    # Setup logging
    setup_logging(
        # level=logging.DEBUG,
        level=logging.INFO,
        log_dir="../logs",
        filename_prefix="dashboard",
        console=True,
        file=True,
    )

    # Create and run the dashboard
    app = DashApp()
    app.run_server(debug=True, port=8050)
    # Add debug logging for chart rendering
    logging.getLogger("tastytrade.dashboard.dashboard").setLevel(logging.DEBUG)

    # Add exception handler to catch and log any rendering errors
    def exception_handler(exc_type, exc_value, exc_traceback):
        logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = exception_handler
