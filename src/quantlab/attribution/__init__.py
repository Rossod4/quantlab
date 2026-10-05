"""Return attribution (M10): where do a committed backtest's monthly returns
come from - market beta, the standard factors, or alpha?

Reads only the series a finished run already produced; never runs a backtest,
never touches the trials registry, never changes a gate."""
