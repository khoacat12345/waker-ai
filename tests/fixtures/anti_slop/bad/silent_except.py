def risky():
    try:
        return int("not-a-number")
    except Exception:
        pass
