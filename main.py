import os
import re
import math
import random
import secrets
import string
import sqlite3
import ipaddress
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from datetime import datetime
from urllib.parse import urlparse

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # app still opens; encryption shows a friendly message
    Fernet = None
    InvalidToken = Exception

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "vaultguard.db")

# ----------------------------------------------------------------- palette
BG = "#0f0d1a"
SURFACE = "#1a1730"
SURFACE2 = "#252142"
LINE = "#352f5c"
TEXT = "#f4f1ff"
MUTED = "#9d96c7"
PINK = "#ff5c93"
VIOLET = "#7c5cff"
MINT = "#3ee6b0"
AMBER = "#ffc247"
DANGER = "#ff5c6c"
HERO = "#2b2166"

FONT = "Helvetica"


def F(size=10, bold=False):
    return (FONT, size, "bold" if bold else "normal")


def lighten(color, amount=0.14):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def human_time(sec):
    if sec < 1:
        return "instantly"
    if sec < 60:
        return f"{sec:.0f} seconds"
    if sec < 3600:
        return f"{sec / 60:.0f} minutes"
    if sec < 86400:
        return f"{sec / 3600:.0f} hours"
    if sec < 86400 * 365:
        return f"{sec / 86400:.0f} days"
    years = sec / (86400 * 365)
    if years < 1000:
        return f"{years:,.0f} years"
    if years < 1e6:
        return "thousands of years"
    if years < 1e9:
        return "millions of years"
    return "billions of years"


# ------------------------------------------------------------ custom widgets
class Pill(tk.Canvas):
    """Fully rounded, hover-aware button drawn on a canvas."""

    def __init__(self, parent, text, command=None, bg=VIOLET, fg="#ffffff",
                 hover=None, size=10, padx=22, pady=10, min_width=0):
        self._font = tkfont.Font(family=FONT, size=size, weight="bold")
        self._bw = max(self._font.measure(text) + padx * 2, min_width)
        self._bh = self._font.metrics("linespace") + pady * 2
        super().__init__(parent, width=self._bw, height=self._bh, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command = text, command
        self.fill, self.fg, self.hover = bg, fg, hover or lighten(bg)
        self._draw(self.fill)
        self.bind("<Enter>", lambda e: self._draw(self.hover))
        self.bind("<Leave>", lambda e: self._draw(self.fill))
        self.bind("<ButtonRelease-1>", self._release)

    def _draw(self, color):
        self.delete("all")
        round_rect(self, 1, 1, self._bw - 1, self._bh - 1, self._bh // 2, fill=color, outline=color)
        self.create_text(self._bw / 2, self._bh / 2, text=self.text, fill=self.fg, font=self._font)

    def _release(self, e):
        if self.command and 0 <= e.x <= self._bw and 0 <= e.y <= self._bh:
            self.command()

    def restyle(self, bg, fg, hover=None):
        self.fill, self.fg, self.hover = bg, fg, hover or lighten(bg)
        self._draw(self.fill)


class Chip(Pill):
    """Toggle chip bound to a BooleanVar."""

    def __init__(self, parent, text, variable):
        super().__init__(parent, text, self._toggle, bg=SURFACE2, fg=MUTED,
                         hover=LINE, size=9, padx=14, pady=6)
        self.var = variable
        self.var.trace_add("write", lambda *_: self._sync())
        self._sync()

    def _toggle(self):
        self.var.set(not self.var.get())

    def _sync(self):
        if self.var.get():
            self.restyle(MINT, "#05261c")
        else:
            self.restyle(SURFACE2, MUTED, LINE)


def card(parent, title=None, subtitle=None, bg=SURFACE):
    frame = tk.Frame(parent, bg=bg, highlightbackground=LINE, highlightthickness=1)
    if title:
        tk.Label(frame, text=title, bg=bg, fg=TEXT, font=F(12, True)).pack(
            anchor="w", padx=18, pady=(16, 2))
    if subtitle:
        tk.Label(frame, text=subtitle, bg=bg, fg=MUTED, font=F(9),
                 wraplength=520, justify="left").pack(anchor="w", padx=18, pady=(0, 8))
    return frame


def caption(parent, text, bg=SURFACE):
    return tk.Label(parent, text=text.upper(), bg=bg, fg=MUTED, font=F(8, True))


def styled_entry(parent, var, show=None, bg=SURFACE2):
    return tk.Entry(parent, textvariable=var, show=show, bg=bg, fg=TEXT,
                    insertbackground=PINK, relief="flat", font=F(11),
                    highlightthickness=2, highlightbackground=bg, highlightcolor=VIOLET)


# --------------------------------------------------------------------- logic
COMMON_PASSWORDS = {
    "password", "123456", "12345678", "123456789", "qwerty", "abc123", "letmein",
    "iloveyou", "admin", "welcome", "monkey", "dragon", "football", "111111",
    "password1", "qwerty123", "sunshine", "princess", "login", "passw0rd",
}


def assess_password(pw):
    """Return a dict describing password strength (computed locally)."""
    pool = 0
    pool += 26 if any(c.islower() for c in pw) else 0
    pool += 26 if any(c.isupper() for c in pw) else 0
    pool += 10 if any(c.isdigit() for c in pw) else 0
    pool += 33 if any(c in string.punctuation for c in pw) else 0
    pool += 100 if any(ord(c) > 127 for c in pw) else 0
    bits = len(pw) * math.log2(pool) if pool else 0
    notes = []
    low = pw.lower()
    common = low in COMMON_PASSWORDS
    if common:
        bits = min(bits, 10)
        notes.append("This is one of the most commonly used passwords.")
    if re.search(r"(.)\1{2,}", pw):
        bits *= 0.8
        notes.append("Repeated characters make it easier to guess.")
    if any(s in low for s in ("123", "abc", "qwerty", "password", "000")):
        bits *= 0.75
        notes.append("Predictable sequences or words were detected.")
    levels = [(28, "Very weak", DANGER), (40, "Weak", "#ff8a5c"), (60, "Fair", AMBER),
              (80, "Strong", MINT), (10 ** 9, "Excellent", "#4ff0ff")]
    for idx, (limit, label, color) in enumerate(levels):
        if bits < limit:
            break
    seconds = (2 ** bits) / 2 / 1e10  # offline attack, 10 billion guesses/sec
    checks = [
        (len(pw) >= 12, "12 or more characters"),
        (any(c.islower() for c in pw) and any(c.isupper() for c in pw), "Upper and lower case"),
        (any(c.isdigit() for c in pw), "Contains a number"),
        (any(not c.isalnum() for c in pw), "Contains a symbol"),
        (not common, "Not a common password"),
    ]
    return {"score": idx, "label": label, "color": color, "bits": bits,
            "crack": human_time(seconds), "checks": checks, "notes": notes}


def generate_password(length, upper, lower, digits, symbols, avoid_lookalike):
    groups = []
    if upper:
        groups.append(string.ascii_uppercase)
    if lower:
        groups.append(string.ascii_lowercase)
    if digits:
        groups.append(string.digits)
    if symbols:
        groups.append("!@#$%^&*()-_=+[]{}?")
    if not groups:
        raise ValueError("Select at least one character type.")
    if avoid_lookalike:
        groups = ["".join(c for c in g if c not in "O0oIl1|") for g in groups]
    chars = [secrets.choice(g) for g in groups]
    pool = "".join(groups)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


BRANDS = {
    "paypal": ("paypal.com",), "google": ("google.com", "google.co.in", "googleapis.com"),
    "microsoft": ("microsoft.com", "live.com", "office.com", "microsoftonline.com"),
    "apple": ("apple.com", "icloud.com"), "icloud": ("icloud.com", "apple.com"),
    "amazon": ("amazon.com", "amazon.in", "amazon.co.uk", "amazonaws.com"),
    "facebook": ("facebook.com", "fb.com"), "instagram": ("instagram.com",),
    "netflix": ("netflix.com",), "whatsapp": ("whatsapp.com",),
    "linkedin": ("linkedin.com",), "dropbox": ("dropbox.com",),
}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "cutt.ly", "rebrand.ly"}
RISKY_TLDS = (".zip", ".mov", ".tk", ".xyz", ".top", ".click", ".gq", ".ml", ".cf", ".work", ".country")
BAIT_WORDS = ["login", "verify", "update", "secure", "account", "password", "wallet",
              "banking", "confirm", "signin", "free", "gift", "prize", "reward", "suspend"]


def scan_url(raw):
    """Return (host, score, findings[(severity, text)]) or None if URL is invalid."""
    candidate = raw if "://" in raw else "http://" + raw
    try:
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if not host or "." not in host:
        return None

    score, found = 0, []

    def add(sev, pts, text):
        nonlocal score
        score += pts
        found.append((sev, text))

    if parsed.scheme != "https":
        add("med", 1, "Connection is not encrypted (no HTTPS).")
    if "@" in parsed.netloc:
        add("high", 3, "Contains '@' - text before it is ignored and can hide the real destination.")
    if len(raw) > 75:
        add("low", 1, "Unusually long address.")
    if len(host.split(".")) >= 5:
        add("med", 1, "Many nested subdomains.")
    try:
        ipaddress.ip_address(host)
        add("high", 3, "Uses a raw IP address instead of a domain name.")
    except ValueError:
        pass
    if "xn--" in host:
        add("high", 3, "Punycode domain - may imitate a known site with look-alike letters.")
    if port and port not in (80, 443):
        add("med", 1, f"Non-standard port ({port}).")
    if host in SHORTENERS:
        add("med", 2, "Link shortener hides the final destination.")
    if host.endswith(RISKY_TLDS):
        add("low", 1, "Domain ending is often abused in scams.")
    if host.count("-") >= 2:
        add("low", 1, "Several hyphens in the domain name.")
    if len(re.findall(r"%[0-9a-fA-F]{2}", raw)) >= 3:
        add("low", 1, "Heavy URL encoding can hide the true address.")
    hits = [w for w in BAIT_WORDS if w in raw.lower()]
    if hits:
        add("med" if len(hits) > 1 else "low", 2 if len(hits) > 1 else 1,
            "Bait words found: " + ", ".join(hits[:5]) + ".")

    normalised = host.translate(str.maketrans("0135", "oles"))
    for brand, official in BRANDS.items():
        legit = any(host == d or host.endswith("." + d) for d in official)
        if brand in host and not legit:
            add("high", 3, f"Mentions '{brand}' but is not an official {brand} domain.")
            break
        if brand in normalised and brand not in host:
            add("high", 3, f"Look-alike spelling of '{brand}' using swapped characters.")
            break
    if not found:
        found.append(("ok", "No common warning signs were found by these basic checks."))
    return host, score, found


# ----------------------------------------------------------------------- app
class VaultGuard(tk.Tk):
    PAGES = ["Home", "Password Lab", "File Vault", "Link Scanner"]

    def __init__(self):
        super().__init__()
        global FONT
        families = set(tkfont.families(self))
        for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "DejaVu Sans", "Helvetica"):
            if name in families:
                FONT = name
                break
        self.title("VaultGuard | Personal Cybersecurity Toolkit")
        self.geometry("1280x780")
        self.minsize(1100, 700)
        self.configure(bg=BG)
        self._init_style()
        self._init_db()
        self._build_shell()
        self.show("Home")

    # ---- styling / database
    def _init_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Vault.Treeview", background=SURFACE, foreground=TEXT,
                    fieldbackground=SURFACE, rowheight=30, borderwidth=0, font=F(9))
        s.configure("Vault.Treeview.Heading", background=SURFACE2, foreground=PINK,
                    relief="flat", font=F(9, True))
        s.map("Vault.Treeview", background=[("selected", VIOLET)], foreground=[("selected", "#ffffff")])

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                category TEXT NOT NULL, item TEXT NOT NULL, result TEXT NOT NULL)""")

    def log(self, category, item, result):
        with sqlite3.connect(DB_PATH) as con:
            con.execute("INSERT INTO activity(timestamp,category,item,result) VALUES(?,?,?,?)",
                        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), category, item[:200], result[:200]))

    def rows(self, limit=50, category=None):
        q = "SELECT timestamp,category,item,result FROM activity"
        args = []
        if category:
            q += " WHERE category=?"
            args.append(category)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with sqlite3.connect(DB_PATH) as con:
            return con.execute(q, args).fetchall()

    def counts(self):
        with sqlite3.connect(DB_PATH) as con:
            return dict(con.execute("SELECT category, COUNT(*) FROM activity GROUP BY category").fetchall())

    def clear_history(self):
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM activity")

    # ---- layout: left sidebar with centred brand and centred page buttons
    def _build_shell(self):
        side = tk.Frame(self, bg=SURFACE, width=250, highlightbackground=LINE, highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        brand = tk.Frame(side, bg=SURFACE)
        brand.pack(fill="x", pady=(34, 10))
        badge = tk.Canvas(brand, width=64, height=64, bg=SURFACE, highlightthickness=0)
        round_rect(badge, 1, 1, 63, 63, 20, fill=PINK, outline=PINK)
        badge.create_text(32, 32, text="V", fill="white", font=F(26, True))
        badge.pack()
        tk.Label(brand, text="VaultGuard", bg=SURFACE, fg=TEXT, font=F(18, True)).pack(pady=(12, 0))
        tk.Label(brand, text="personal security toolkit", bg=SURFACE, fg=MUTED, font=F(9)).pack()

        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=28, pady=(22, 20))

        foot = tk.Frame(side, bg=SURFACE)
        foot.pack(side="bottom", fill="x", pady=24)
        tk.Label(foot, text="\u25CF  LOCAL MODE", bg=SURFACE, fg=MINT, font=F(8, True)).pack()
        tk.Label(foot, text="Your data stays on this device", bg=SURFACE, fg=MUTED, font=F(8)).pack(pady=(4, 0))

        navbox = tk.Frame(side, bg=SURFACE)
        navbox.pack(fill="x")
        self.nav = {}
        for name in self.PAGES:
            pill = Pill(navbox, name, lambda n=name: self.show(n), bg=SURFACE, fg=MUTED,
                        hover=SURFACE2, size=11, pady=12, min_width=200)
            pill.pack(pady=5)
            self.nav[name] = pill

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=28, pady=24)

    def show(self, name):
        for label, pill in self.nav.items():
            if label == name:
                pill.restyle(VIOLET, "#ffffff")
            else:
                pill.restyle(SURFACE, MUTED, SURFACE2)
        for child in self.content.winfo_children():
            child.destroy()
        page = {"Home": HomePage, "Password Lab": PasswordPage,
                "File Vault": FilePage, "Link Scanner": LinkPage}[name]
        page(self, self.content).pack(fill="both", expand=True)


# --------------------------------------------------------------------- pages
TIPS = [
    "Use a different password for every account - a password manager makes this easy.",
    "Hover over a link before clicking. If the domain looks odd, do not open it.",
    "Turn on two-factor authentication for email and banking first.",
    "Back up encrypted files and store their keys in a different place.",
    "Banks and companies never ask for your password by email or text.",
]


class HomePage(tk.Frame):
    CAT_COLORS = {"Password": PINK, "File": MINT, "URL": AMBER}

    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        counts = app.counts()
        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

        # ---- hero banner
        hero = tk.Frame(self, bg=HERO, highlightbackground=VIOLET, highlightthickness=1)
        hero.pack(fill="x", pady=(0, 16))
        left = tk.Frame(hero, bg=HERO)
        left.pack(side="left", padx=26, pady=18)
        tk.Label(left, text=f"{greet}.", bg=HERO, fg=TEXT, font=F(24, True)).pack(anchor="w")
        tk.Label(left, text=datetime.now().strftime("%A, %d %B %Y"), bg=HERO, fg="#cfc8ff",
                 font=F(10)).pack(anchor="w", pady=(2, 8))
        tk.Label(left, text="Tip: " + random.choice(TIPS), bg=HERO, fg=AMBER, font=F(10),
                 wraplength=520, justify="left").pack(anchor="w")
        total = sum(counts.values())
        stat = tk.Frame(hero, bg=HERO)
        stat.pack(side="right", padx=34)
        tk.Label(stat, text=str(total), bg=HERO, fg=TEXT, font=F(34, True)).pack()
        tk.Label(stat, text="TOTAL CHECKS", bg=HERO, fg="#cfc8ff", font=F(8, True)).pack()

        # ---- three tool cards
        tools = tk.Frame(self, bg=BG)
        tools.pack(fill="x", pady=(0, 16))
        specs = [
            ("***", "Password Lab", "Test how strong a password is and generate safe ones.",
             "Password", "checked", PINK),
            ("ENC", "File Vault", "Lock any file with encryption and unlock it with its key.",
             "File", "operations", MINT),
            ("URL", "Link Scanner", "Spot phishing signs in a link before you click it.",
             "URL", "scanned", AMBER),
        ]
        for i, (icon, title, desc, key, unit, color) in enumerate(specs):
            tools.grid_columnconfigure(i, weight=1, uniform="tool")
            c = tk.Frame(tools, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 2 else 8))
            badge = tk.Canvas(c, width=52, height=52, bg=SURFACE, highlightthickness=0)
            round_rect(badge, 1, 1, 51, 51, 16, fill=color, outline=color)
            badge.create_text(26, 26, text=icon, fill="#0f0d1a", font=F(11, True))
            badge.pack(anchor="w", padx=18, pady=(18, 10))
            tk.Label(c, text=title, bg=SURFACE, fg=TEXT, font=F(13, True)).pack(anchor="w", padx=18)
            tk.Label(c, text=desc, bg=SURFACE, fg=MUTED, font=F(9), wraplength=210,
                     justify="left", height=3, anchor="nw").pack(anchor="w", padx=18, pady=(4, 6))
            tk.Label(c, text=f"{counts.get(key, 0)} {unit}", bg=SURFACE, fg=color,
                     font=F(10, True)).pack(anchor="w", padx=18)
            Pill(c, "Open", lambda t=title: app.show(t), bg=SURFACE2, hover=LINE,
                 size=9, padx=22, pady=7).pack(anchor="w", padx=18, pady=(10, 18))

        # ---- bottom: recent activity + donut chart
        lower = tk.Frame(self, bg=BG)
        lower.pack(fill="both", expand=True)
        recent = card(lower, "Recent activity", "Stored only on this computer.")
        recent.pack(side="left", fill="both", expand=True, padx=(0, 14))
        rows = app.rows(6)
        if not rows:
            tk.Label(recent, text="No activity yet - open a tool above to get started.",
                     bg=SURFACE, fg=MUTED, font=F(10)).pack(anchor="w", padx=18, pady=20)
        for ts, cat, item, res in rows:
            line = tk.Frame(recent, bg=SURFACE)
            line.pack(fill="x", padx=18, pady=4)
            tk.Label(line, text=cat.upper(), bg=self.CAT_COLORS.get(cat, VIOLET), fg="#0f0d1a",
                     font=F(7, True), width=9, pady=3).pack(side="left")
            tk.Label(line, text=item[:30], bg=SURFACE, fg=TEXT, font=F(10)).pack(side="left", padx=12)
            tk.Label(line, text=ts[5:16], bg=SURFACE, fg=MUTED, font=F(9)).pack(side="right")
            tk.Label(line, text=res[:22], bg=SURFACE, fg=MUTED, font=F(9)).pack(side="right", padx=14)
        foot = tk.Frame(recent, bg=SURFACE)
        foot.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        Pill(foot, "Clear history", self.clear, bg=SURFACE2, fg=DANGER, hover=LINE,
             size=9, padx=16, pady=7).pack(side="left")

        mix = card(lower, "Activity mix")
        mix.pack(side="left", fill="y")
        donut = tk.Canvas(mix, width=210, height=210, bg=SURFACE, highlightthickness=0)
        donut.pack(padx=40, pady=(6, 6))
        parts = [(counts.get(k, 0), c) for k, c in (("Password", PINK), ("File", MINT), ("URL", AMBER))]
        box = (22, 22, 188, 188)
        donut.create_arc(*box, start=0, extent=359.9, style="arc", width=24, outline=SURFACE2)
        if total:
            start = 90.0
            active = sum(1 for n, _ in parts if n)
            for n, color in parts:
                if not n:
                    continue
                extent = -(360.0 * n / total)
                gap = 4 if active > 1 else 0
                donut.create_arc(*box, start=start, extent=min(extent + gap, -1) if gap else -359.9,
                                 style="arc", width=24, outline=color)
                start += extent
        donut.create_text(105, 98, text=str(total), fill=TEXT, font=F(26, True))
        donut.create_text(105, 126, text="actions", fill=MUTED, font=F(9))
        legend = tk.Frame(mix, bg=SURFACE)
        legend.pack(pady=(0, 16))
        for (label, color), (n, _) in zip((("Passwords", PINK), ("Files", MINT), ("Links", AMBER)), parts):
            r = tk.Frame(legend, bg=SURFACE)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="\u25CF", bg=SURFACE, fg=color, font=F(11)).pack(side="left")
            tk.Label(r, text=label, bg=SURFACE, fg=TEXT, font=F(10)).pack(side="left", padx=8)
            tk.Label(r, text=str(n), bg=SURFACE, fg=MUTED, font=F(10, True)).pack(side="right", padx=(30, 0))

    def clear(self):
        if messagebox.askyesno("Clear history", "Delete all saved activity? This cannot be undone."):
            self.app.clear_history()
            self.app.show("Home")


class PasswordPage(tk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        left = card(self, "Strength tester", "Analysed live on your device. Nothing is saved or sent.")
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))
        right = card(self, "Password generator")
        right.pack(side="left", fill="y")

        # ---- tester
        caption(left, "Type a password").pack(anchor="w", padx=18, pady=(6, 6))
        row = tk.Frame(left, bg=SURFACE)
        row.pack(fill="x", padx=18)
        self.pw = tk.StringVar()
        self.entry = styled_entry(row, self.pw, show="*")
        self.entry.pack(side="left", fill="x", expand=True, ipady=9)
        self.show_var = tk.BooleanVar(value=False)
        self.show_var.trace_add("write", lambda *_: self.entry.config(show="" if self.show_var.get() else "*"))
        Chip(row, "Show", self.show_var).pack(side="left", padx=(10, 0))

        self.meter = tk.Canvas(left, height=14, bg=SURFACE, highlightthickness=0)
        self.meter.pack(fill="x", padx=18, pady=(18, 6))
        self.meter.bind("<Configure>", lambda e: self.update_view())
        self.verdict = tk.Label(left, text="Start typing...", bg=SURFACE, fg=MUTED, font=F(18, True))
        self.verdict.pack(anchor="w", padx=18)
        self.detail = tk.Label(left, text="", bg=SURFACE, fg=MUTED, font=F(10))
        self.detail.pack(anchor="w", padx=18, pady=(2, 10))
        self.check_labels = []
        for _ in range(5):
            lbl = tk.Label(left, text="", bg=SURFACE, fg=MUTED, font=F(10))
            lbl.pack(anchor="w", padx=18, pady=1)
            self.check_labels.append(lbl)
        self.notes = tk.Label(left, text="", bg=SURFACE, fg=AMBER, font=F(9), wraplength=330, justify="left")
        self.notes.pack(anchor="w", padx=18, pady=(10, 8))
        Pill(left, "Save result to history", self.save_result, bg=PINK).pack(anchor="w", padx=18, pady=(4, 18))
        self.pw.trace_add("write", lambda *_: self.update_view())
        self.entry.bind("<Return>", lambda e: self.save_result())

        # ---- generator
        wrap = tk.Frame(right, bg=SURFACE, width=410)
        wrap.pack(padx=18, pady=(6, 18))
        caption(wrap, "Length").pack(anchor="w", pady=(0, 4))
        self.length = tk.IntVar(value=18)
        slider_row = tk.Frame(wrap, bg=SURFACE)
        slider_row.pack(fill="x")
        tk.Scale(slider_row, from_=8, to=64, orient="horizontal", variable=self.length, showvalue=0,
                 bg=SURFACE, troughcolor=SURFACE2, highlightthickness=0, bd=0, sliderrelief="flat",
                 activebackground=PINK, length=300, command=lambda v: self.generate()).pack(side="left")
        self.len_label = tk.Label(slider_row, textvariable=self.length, bg=SURFACE, fg=PINK, font=F(14, True), width=3)
        self.len_label.pack(side="left", padx=8)

        caption(wrap, "Character types").pack(anchor="w", pady=(14, 6))
        chips = tk.Frame(wrap, bg=SURFACE)
        chips.pack(anchor="w")
        self.opts = {k: tk.BooleanVar(value=True) for k in ("upper", "lower", "digits", "symbols")}
        self.opts["lookalike"] = tk.BooleanVar(value=False)
        for i, (key, text) in enumerate([("upper", "ABC"), ("lower", "abc"), ("digits", "123"), ("symbols", "#$%")]):
            Chip(chips, text, self.opts[key]).grid(row=0, column=i, padx=(0, 8), pady=2)
            self.opts[key].trace_add("write", lambda *_: self.generate())
        Chip(wrap, "Avoid look-alikes (O/0, l/1)", self.opts["lookalike"]).pack(anchor="w", pady=(8, 0))
        self.opts["lookalike"].trace_add("write", lambda *_: self.generate())

        self.out = tk.StringVar()
        out_entry = styled_entry(wrap, self.out, bg=BG)
        out_entry.config(font=(FONT, 12), state="readonly", readonlybackground=BG)
        out_entry.pack(fill="x", pady=(20, 8), ipady=11)
        self.out_info = tk.Label(wrap, text="", bg=SURFACE, fg=MUTED, font=F(9))
        self.out_info.pack(anchor="w")
        btns = tk.Frame(wrap, bg=SURFACE)
        btns.pack(anchor="w", pady=(14, 0))
        Pill(btns, "New password", self.generate, bg=VIOLET).pack(side="left")
        Pill(btns, "Copy", self.copy, bg=MINT, fg="#05261c").pack(side="left", padx=10)
        tk.Label(wrap, text="Clipboard is wiped 30 seconds after copying.", bg=SURFACE, fg=MUTED,
                 font=F(8)).pack(anchor="w", pady=(12, 0))
        self.generate()
        self.update_view()

    def update_view(self):
        pw = self.pw.get()
        r = assess_password(pw) if pw else None
        w = max(self.meter.winfo_width(), 100)
        self.meter.delete("all")
        seg = (w - 4 * 6) / 5
        for i in range(5):
            on = r is not None and i <= r["score"]
            color = r["color"] if on else SURFACE2
            round_rect(self.meter, i * (seg + 6), 0, i * (seg + 6) + seg, 14, 7, fill=color, outline=color)
        if not r:
            self.verdict.config(text="Start typing...", fg=MUTED)
            self.detail.config(text="")
            self.notes.config(text="")
            for lbl in self.check_labels:
                lbl.config(text="")
            return
        self.verdict.config(text=r["label"], fg=r["color"])
        self.detail.config(text=f"~{r['bits']:.0f} bits of entropy  |  offline crack time: {r['crack']}")
        for lbl, (ok, text) in zip(self.check_labels, r["checks"]):
            lbl.config(text=("\u2714  " if ok else "\u2718  ") + text, fg=MINT if ok else MUTED)
        self.notes.config(text="\n".join(r["notes"]))

    def save_result(self):
        pw = self.pw.get()
        if not pw:
            messagebox.showwarning("Nothing to save", "Type a password first.")
            return
        r = assess_password(pw)
        self.app.log("Password", "Strength test", r["label"])  # password itself is never stored
        messagebox.showinfo("Saved", f"Result '{r['label']}' saved to your history.\nThe password itself was not stored.")

    def generate(self, *_):
        o = self.opts
        try:
            pw = generate_password(int(self.length.get()), o["upper"].get(), o["lower"].get(),
                                   o["digits"].get(), o["symbols"].get(), o["lookalike"].get())
        except ValueError:
            self.out.set("")
            self.out_info.config(text="Select at least one character type.", fg=AMBER)
            return
        self.out.set(pw)
        r = assess_password(pw)
        self.out_info.config(text=f"{r['label']}  |  ~{r['bits']:.0f} bits", fg=r["color"])

    def copy(self):
        value = self.out.get()
        if not value:
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        self.out_info.config(text="Copied! Clipboard clears in 30 s.", fg=MINT)
        self.after(30000, lambda: self._wipe(value))

    def _wipe(self, value):
        try:
            if self.clipboard_get() == value:
                self.clipboard_clear()
        except tk.TclError:
            pass


class FilePage(tk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        self.src = self.enc = self.key = None

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, 14))
        self.btn_enc = Pill(top, "Encrypt", lambda: self.switch("enc"), min_width=130)
        self.btn_dec = Pill(top, "Decrypt", lambda: self.switch("dec"), min_width=130)
        self.btn_enc.pack(side="left", padx=(0, 8))
        self.btn_dec.pack(side="left")
        warn = tk.Label(top, text="\u26A0  Keep the .key file separate from the encrypted file. No key = no recovery.",
                        bg=BG, fg=AMBER, font=F(9, True))
        warn.pack(side="right")

        self.panel = tk.Frame(self, bg=BG)
        self.panel.pack(fill="both", expand=True)
        self.status = tk.Label(self, text="Ready.", bg=BG, fg=MUTED, font=F(10), anchor="w")
        self.status.pack(fill="x", pady=(10, 0))
        self.switch("enc")

    def say(self, text, color=MUTED):
        self.status.config(text=text, fg=color)

    def step(self, parent, number, title, desc):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", padx=22, pady=10)
        badge = tk.Canvas(row, width=38, height=38, bg=SURFACE, highlightthickness=0)
        badge.create_oval(1, 1, 37, 37, fill=VIOLET, outline=VIOLET)
        badge.create_text(19, 19, text=str(number), fill="white", font=F(13, True))
        badge.pack(side="left", padx=(0, 14))
        txt = tk.Frame(row, bg=SURFACE)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=title, bg=SURFACE, fg=TEXT, font=F(11, True)).pack(anchor="w")
        value = tk.StringVar(value=desc)
        tk.Label(txt, textvariable=value, bg=SURFACE, fg=MUTED, font=F(9), anchor="w").pack(anchor="w")
        action = tk.Frame(row, bg=SURFACE)
        action.pack(side="right")
        return action, value

    def switch(self, mode):
        for child in self.panel.winfo_children():
            child.destroy()
        if mode == "enc":
            self.btn_enc.restyle(PINK, "#ffffff")
            self.btn_dec.restyle(SURFACE2, MUTED, LINE)
            c = card(self.panel, "Encrypt a file", "Creates an .enc file plus a separate .key file.")
            c.pack(fill="both", expand=True)
            a1, self.v_src = self.step(c, 1, "Choose the file", "No file selected")
            Pill(a1, "Browse...", self.pick_src, bg=SURFACE2, hover=LINE).pack()
            a2, _ = self.step(c, 2, "Encrypt and save", "You will choose where to save the .enc and .key files.")
            Pill(a2, "Encrypt now", self.do_encrypt, bg=MINT, fg="#05261c").pack()
        else:
            self.btn_dec.restyle(PINK, "#ffffff")
            self.btn_enc.restyle(SURFACE2, MUTED, LINE)
            c = card(self.panel, "Decrypt a file", "You need both the .enc file and its matching .key file.")
            c.pack(fill="both", expand=True)
            a1, self.v_enc = self.step(c, 1, "Choose the encrypted file", "No file selected")
            Pill(a1, "Browse...", self.pick_enc, bg=SURFACE2, hover=LINE).pack()
            a2, self.v_key = self.step(c, 2, "Choose the key file", "No key selected")
            Pill(a2, "Browse...", self.pick_key, bg=SURFACE2, hover=LINE).pack()
            a3, _ = self.step(c, 3, "Decrypt and save", "You will choose where to save the recovered file.")
            Pill(a3, "Decrypt now", self.do_decrypt, bg=MINT, fg="#05261c").pack()
        self.say("Ready.")

    # ---- pickers
    def pick_src(self):
        p = filedialog.askopenfilename(title="Select a file to encrypt")
        if p:
            self.src = p
            self.v_src.set(f"{os.path.basename(p)}  ({human_size(os.path.getsize(p))})")

    def pick_enc(self):
        p = filedialog.askopenfilename(title="Select encrypted file",
                                       filetypes=[("Encrypted", "*.enc"), ("All files", "*.*")])
        if p:
            self.enc = p
            self.v_enc.set(os.path.basename(p))

    def pick_key(self):
        p = filedialog.askopenfilename(title="Select key file", filetypes=[("Key", "*.key"), ("All files", "*.*")])
        if p:
            self.key = p
            self.v_key.set(os.path.basename(p))

    # ---- actions
    def _need_crypto(self):
        if Fernet is None:
            messagebox.showerror("Missing package", "Install it first:\npython -m pip install cryptography")
            return False
        return True

    def do_encrypt(self):
        if not self._need_crypto():
            return
        if not self.src:
            messagebox.showwarning("No file", "Choose a file to encrypt first.")
            return
        out = filedialog.asksaveasfilename(title="Save encrypted file as", defaultextension=".enc",
                                           initialdir=os.path.dirname(self.src),
                                           initialfile=os.path.basename(self.src) + ".enc",
                                           filetypes=[("Encrypted", "*.enc")])
        if not out:
            return
        key_out = filedialog.asksaveasfilename(title="Save the key (store it somewhere safe)",
                                               defaultextension=".key",
                                               initialfile=os.path.basename(out) + ".key",
                                               filetypes=[("Key", "*.key")])
        if not key_out:
            return
        if os.path.abspath(out) == os.path.abspath(self.src):
            messagebox.showerror("Unsafe path", "The output cannot overwrite the original file.")
            return
        try:
            key = Fernet.generate_key()
            with open(self.src, "rb") as f:
                token = Fernet(key).encrypt(f.read())
            with open(out, "wb") as f:
                f.write(token)
            with open(key_out, "wb") as f:
                f.write(key)
            try:
                os.chmod(key_out, 0o600)
            except OSError:
                pass
            self.app.log("File", os.path.basename(self.src), "Encrypted")
            self.say(f"\u2714 Encrypted -> {os.path.basename(out)}   |   key -> {os.path.basename(key_out)}", MINT)
        except OSError as exc:
            self.say(f"\u2718 File error: {exc}", DANGER)

    def do_decrypt(self):
        if not self._need_crypto():
            return
        if not self.enc or not self.key:
            messagebox.showwarning("Missing files", "Choose both the encrypted file and its key.")
            return
        base = os.path.basename(self.enc)
        out = filedialog.asksaveasfilename(title="Save decrypted file as",
                                           initialfile=base[:-4] if base.endswith(".enc") else base + ".dec")
        if not out:
            return
        try:
            with open(self.key, "rb") as f:
                key = f.read().strip()
            with open(self.enc, "rb") as f:
                data = Fernet(key).decrypt(f.read())
            with open(out, "wb") as f:
                f.write(data)
            self.app.log("File", base, "Decrypted")
            self.say(f"\u2714 Decrypted -> {os.path.basename(out)}", MINT)
        except (InvalidToken, ValueError):
            self.say("\u2718 Wrong key, or the encrypted file was modified.", DANGER)
        except OSError as exc:
            self.say(f"\u2718 File error: {exc}", DANGER)


class LinkPage(tk.Frame):
    SEV = {"high": (DANGER, "HIGH"), "med": (AMBER, "MEDIUM"), "low": (MUTED, "LOW"), "ok": (MINT, "OK")}

    def __init__(self, app, parent):
        super().__init__(parent, bg=BG)
        self.app = app
        bar = card(self, "Link scanner", "Paste a web address. Checks run offline and never open the site.")
        bar.pack(fill="x", pady=(0, 14))
        row = tk.Frame(bar, bg=SURFACE)
        row.pack(fill="x", padx=18, pady=(4, 18))
        self.url = tk.StringVar()
        entry = styled_entry(row, self.url)
        entry.pack(side="left", fill="x", expand=True, ipady=10)
        entry.bind("<Return>", lambda e: self.scan())
        Pill(row, "Paste", self.paste, bg=SURFACE2, hover=LINE).pack(side="left", padx=(10, 0))
        Pill(row, "Scan link", self.scan, bg=PINK).pack(side="left", padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.result = card(body, "Result")
        self.result.pack(side="left", fill="both", expand=True, padx=(0, 14))
        self.verdict = tk.Label(self.result, text="Waiting for a link", bg=SURFACE, fg=MUTED, font=F(20, True))
        self.verdict.pack(anchor="w", padx=18, pady=(6, 0))
        self.host_lbl = tk.Label(self.result, text="", bg=SURFACE, fg=MUTED, font=F(10))
        self.host_lbl.pack(anchor="w", padx=18)
        self.gauge = tk.Canvas(self.result, height=30, bg=SURFACE, highlightthickness=0)
        self.gauge.pack(fill="x", padx=18, pady=14)
        self.gauge.bind("<Configure>", lambda e: self.draw_gauge(self._score))
        self._score = None
        self.findings = tk.Frame(self.result, bg=SURFACE)
        self.findings.pack(fill="both", expand=True, padx=18)
        tk.Label(self.result, text="Heuristic check only - not a guarantee that a site is safe.",
                 bg=SURFACE, fg=MUTED, font=F(8)).pack(anchor="w", padx=18, pady=(8, 14))

        hist = card(body, "Recent scans")
        hist.pack(side="left", fill="both")
        self.tree = ttk.Treeview(hist, columns=("t", "h", "r"), show="headings", style="Vault.Treeview", height=12)
        for col, head, w in [("t", "TIME", 70), ("h", "HOST", 170), ("r", "VERDICT", 100)]:
            self.tree.heading(col, text=head)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.load_history()

    def paste(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def draw_gauge(self, score):
        g = self.gauge
        g.delete("all")
        w = max(g.winfo_width(), 120)
        third = (w - 8) / 3
        for i, color in enumerate((MINT, AMBER, DANGER)):
            round_rect(g, i * (third + 4), 10, i * (third + 4) + third, 22, 6, fill=color, outline=color)
        if score is not None:
            x = 4 + (w - 8) * min(score, 9) / 9
            g.create_polygon(x - 7, 0, x + 7, 0, x, 11, fill=TEXT, outline=TEXT)

    def scan(self):
        raw = self.url.get().strip()
        if not raw:
            messagebox.showwarning("No link", "Paste a web address to scan.")
            return
        res = scan_url(raw)
        if res is None:
            messagebox.showerror("Invalid link", "Enter a valid address such as https://example.com")
            return
        host, score, found = res
        if score >= 6:
            label, color = "High risk", DANGER
        elif score >= 3:
            label, color = "Be careful", AMBER
        else:
            label, color = "No obvious red flags", MINT
        self.verdict.config(text=label, fg=color)
        self.host_lbl.config(text=f"{host}   |   risk score {score}")
        self._score = score
        self.draw_gauge(score)
        for child in self.findings.winfo_children():
            child.destroy()
        for sev, text in found:
            color_s, tag = self.SEV[sev]
            line = tk.Frame(self.findings, bg=SURFACE)
            line.pack(fill="x", pady=3)
            tk.Label(line, text=tag, bg=color_s, fg="#0f0d1a" if sev != "low" else TEXT, font=F(7, True),
                     width=7, pady=2).pack(side="left", anchor="n")
            tk.Label(line, text=text, bg=SURFACE, fg=TEXT, font=F(10), wraplength=380,
                     justify="left").pack(side="left", padx=10)
        self.app.log("URL", host, label)
        self.load_history()

    def load_history(self):
        self.tree.delete(*self.tree.get_children())
        for ts, _, item, res in self.app.rows(12, "URL"):
            self.tree.insert("", "end", values=(ts[11:], item[:26], res))


if __name__ == "__main__":
    VaultGuard().mainloop()
