# src/tastytrade/dashboard/app.py

if __name__ == "__main__":
    import logging

    from tastytrade.dashboard.dashboard import DashApp
    from tastytrade.logging import setup_logging

    # Setup logging
    setup_logging(
        level=logging.INFO,
        log_dir="../logs",
        filename_prefix="dashboard",
        console=True,
        file=True,
    )

    # Create and run the dashboard
    app = DashApp()
    app.run_server(debug=True, port=8050)
