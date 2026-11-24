import time
from config import MODE
from indicators import klines
from utils import log

def catch_up(bot, save_state):
    """Shadow mode: bot ruka raha toh miss hue 1H candles par open positions replay karo."""
    if MODE != "shadow" or not bot.S["pos"]:
        return
    row = bot.db.c.execute("select max(bar) from equity").fetchone()
    last_done = row[0] if row else None
    now_bar = int(time.time() // 3600) * 3600
    if not last_done or now_bar - last_done < 2 * 3600:
        return
    log(f"CATCH-UP: bot ~{(now_bar - last_done) // 3600}h band tha, {len(bot.S['pos'])} positions replay ho rahi hain")
    for s in list(bot.S["pos"]):
        x = bot.S["pos"][s]
        x.setdefault("side", "long")
        x.setdefault("ext", x.get("highest", x["entry"]))
        d1 = klines(bot.cl, s, "1h", 1000)
        d4 = klines(bot.cl, s, "4h", 1000)
        for t in [i for i in d1.index if i / 1000 >= last_done]:
            bar = d1.loc[t]
            ct, close = int(bar["ct"]), float(bar["close"])
            out = bot.broker.sweep({s: bar.to_dict()}, [s])
            if out:
                bot.finish(s, out[0][1], "stop")
                break
            why = bot.manage_one(s, x, d1[d1["ct"] <= ct], d4[d4["ct"] <= ct], close)
            if why:
                bot.finish(s, bot.broker.close(s, close, why), why)
                break
    bot.S["cash"], bot.S["spos"] = bot.broker.cash, bot.broker.pos
    save_state(bot.S)