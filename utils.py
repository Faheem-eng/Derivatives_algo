import time
from decimal import Decimal, ROUND_DOWN

def floor_to(x, step):
    return (x / step).to_integral_value(rounding=ROUND_DOWN) * step

def fmt(d):
    return format(Decimal(d).normalize(), "f")

def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC | " + " ".join(str(x) for x in a)
    print(line, flush=True)
    try:
        with open("bot.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass