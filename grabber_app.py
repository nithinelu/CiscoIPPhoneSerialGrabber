"""CiscoIPPhoneSerialGrabber - Tkinter front end for grabber_engine.

Copyright (c) 2026 Nithin Eluvathingal. MIT License - see LICENSE.
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import grabber_engine as E

APP_NAME = "CiscoIPPhoneSerialGrabber"
APP_TITLE = "Cisco IP Phone Serial Grabber"
APP_TAGLINE = "Serial numbers, MACs and models from Cisco IP phones on the network"
AUTHOR = "Nithin Eluvathingal"
CREDIT = f"© 2026 {AUTHOR} · MIT License"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
SETTINGS_DIR = os.path.join(_APPDATA, APP_NAME)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
DEFAULTS = {"targets": "", "cucm_host": "", "cucm_user": "", "cucm_status": "Registered", "workers": 64,
            "timeout": 4.0, "https": True, "phone_user": ""}

C = {"bg": "#F3F6FA", "surface": "#FFFFFF", "ink": "#1E2A38", "muted": "#6B7785", "line": "#D6DDE6",
     "stripe": "#F7F9FC", "accent": "#049FD9", "accent_dark": "#0379A6", "accent_soft": "#DDF2FB",
     "navy": "#0B2A4A", "good": "#1E7B45", "warn": "#8A5A00", "err": "#B42318"}
F = "Segoe UI"


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in s})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)  # passwords are never saved
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} — {APP_TAGLINE}")
        self.geometry("1440x860")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.minsize(1100, 640)
        self.configure(bg=C["bg"])
        self.settings = load_settings()
        self.results = []
        self.extra = {}            # ip -> CUCM fields from discovery
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.sort_col, self.sort_rev = None, False
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._drain)

    # ------------------------------------------------------------------------------------------- look
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", font=(F, 10), background=C["bg"], foreground=C["ink"])
        st.configure("Card.TFrame", background=C["surface"])
        st.configure("Card.TLabel", background=C["surface"])
        st.configure("Muted.TLabel", background=C["surface"], foreground=C["muted"], font=(F, 9))
        st.configure("H.TLabel", background=C["surface"], font=(F, 11, "bold"), foreground=C["navy"])
        st.configure("Foot.TLabel", background=C["bg"], foreground=C["muted"], font=(F, 9))
        st.configure("Stat.TLabel", background=C["surface"], font=(F, 10, "bold"), foreground=C["navy"])
        st.configure("Card.TCheckbutton", background=C["surface"])
        st.configure("Treeview", rowheight=24, fieldbackground=C["surface"], background=C["surface"],
                     bordercolor=C["line"])
        st.configure("Treeview.Heading", background="#E9EEF4", foreground=C["ink"], font=(F, 9, "bold"),
                     relief="flat")
        st.map("Treeview", background=[("selected", C["accent_soft"])], foreground=[("selected", C["ink"])])
        st.configure("Accent.TButton", background=C["accent"], foreground="white", borderwidth=0, padding=(12, 5))
        st.map("Accent.TButton", background=[("active", C["accent_dark"]), ("disabled", "#9CCFE3")])
        st.configure("TButton", padding=(8, 3))
        st.configure("Head.TButton", background="#17406A", foreground="white", borderwidth=0, padding=(10, 5))
        st.map("Head.TButton", background=[("active", C["accent"])])
        st.configure("Horizontal.TProgressbar", troughcolor=C["line"], background=C["accent"])

    def _card(self, parent, title=None, **pack):
        outer = tk.Frame(parent, bg=C["line"], padx=1, pady=1)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=10)
        inner.pack(fill="both", expand=True)
        if title:
            ttk.Label(inner, text=title, style="H.TLabel").pack(anchor="w", pady=(0, 6))
        if pack:
            outer.pack(**pack)
        return outer, inner

    # ------------------------------------------------------------------------------------------- layout
    def _build(self):
        head = tk.Frame(self, bg=C["navy"], padx=16, pady=10)
        head.pack(fill="x")
        tl = tk.Frame(head, bg=C["navy"])
        tl.pack(side="left")
        tk.Label(tl, text=APP_TITLE, bg=C["navy"], fg="white", font=(F, 18, "bold")).pack(anchor="w")
        tk.Label(tl, text=f"{APP_TAGLINE}   ·   by {AUTHOR}", bg=C["navy"], fg="#C9DCEC",
                 font=(F, 9)).pack(anchor="w")
        for txt, cmd in [("Export CSV", lambda: self.export("csv")), ("Export Excel", lambda: self.export("xlsx")),
                         ("Copy serials", self.copy_serials), ("Clear results", self.clear_results)]:
            ttk.Button(head, text=txt, style="Head.TButton", command=cmd).pack(side="right", padx=3)

        body = tk.Frame(self, bg=C["bg"], padx=12, pady=10)
        body.pack(fill="both", expand=True)
        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=0)
        panes.add(right, weight=1)
        self._build_left(left)
        self._build_right(right)

        foot = ttk.Frame(self, padding=(14, 4))
        foot.pack(fill="x")
        ttk.Label(foot, text=CREDIT, style="Foot.TLabel").pack(side="left")
        ttk.Label(foot, text="Phones must have 'Web Access' enabled (CUCM › Phone › Product Specific Configuration).",
                  style="Foot.TLabel").pack(side="right")

    def _build_left(self, parent):
        s = self.settings
        # targets
        tgt_outer, c = self._card(parent, "1 · Targets")
        ttk.Label(c, text="IPs, ranges (10.1.1.10-50) or subnets (10.1.1.0/24)",
                  style="Muted.TLabel").pack(anchor="w")
        tf = ttk.Frame(c, style="Card.TFrame")
        tf.pack(fill="both", expand=True, pady=(4, 4))
        self.t_targets = tk.Text(tf, height=4, width=40, font=("Consolas", 10), relief="flat",
                                 highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["accent"],
                                 undo=True)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.t_targets.yview)
        self.t_targets.configure(yscrollcommand=sb.set)
        self.t_targets.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.t_targets.insert("1.0", s["targets"])
        self.t_targets.bind("<<Modified>>", self._targets_changed)
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Load file…", command=self.load_file).pack(side="left")
        ttk.Button(row, text="Clear", command=self.clear_targets).pack(side="left", padx=4)
        self.lbl_count = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_count.pack(side="right")

        # CUCM
        cucm_outer, c = self._card(parent, "2 · Or discover from CUCM (optional)")
        self.v_host = tk.StringVar(value=s["cucm_host"])
        self.v_user = tk.StringVar(value=s["cucm_user"])
        self.v_pw = tk.StringVar()
        self.v_cstatus = tk.StringVar(value=s["cucm_status"])
        g = ttk.Frame(c, style="Card.TFrame")
        g.pack(fill="x")
        for r, (lab, var, kw) in enumerate([("CUCM node", self.v_host, {}), ("User", self.v_user, {}),
                                            ("Password", self.v_pw, {"show": "•"})]):
            ttk.Label(g, text=lab, style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(g, textvariable=var, width=24, **kw).grid(row=r, column=1, sticky="ew", pady=2, padx=(6, 0))
        ttk.Label(g, text="Phones", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Combobox(g, textvariable=self.v_cstatus, values=["Registered", "Any"], state="readonly",
                     width=12).grid(row=3, column=1, sticky="w", pady=2, padx=(6, 0))
        g.columnconfigure(1, weight=1)
        self.btn_cucm = ttk.Button(c, text="Discover phones (RisPort)", command=self.discover)
        self.btn_cucm.pack(anchor="w", pady=(6, 0))
        ttk.Label(c, text="Adds each phone's IP to the targets, with its\ndevice name, DN and description.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        # options
        scan_outer, c = self._card(parent, "3 · Scan")
        self.v_workers = tk.StringVar(value=str(s["workers"]))
        self.v_timeout = tk.StringVar(value=f"{s['timeout']:g}")
        self.v_https = tk.BooleanVar(value=s["https"])
        self.v_puser = tk.StringVar(value=s["phone_user"])
        self.v_ppw = tk.StringVar()
        g = ttk.Frame(c, style="Card.TFrame")
        g.pack(fill="x")
        ttk.Label(g, text="Parallel", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(g, from_=1, to=256, increment=16, textvariable=self.v_workers, width=6).grid(
            row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(g, text="Timeout s", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(g, from_=1, to=30, increment=1, textvariable=self.v_timeout, width=5).grid(
            row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Checkbutton(g, text="Also try HTTPS (443)", variable=self.v_https, style="Card.TCheckbutton").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(g, text="Phone web login (only if pages ask for one):", style="Muted.TLabel").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Entry(g, textvariable=self.v_puser, width=12).grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Entry(g, textvariable=self.v_ppw, width=12, show="•").grid(row=3, column=2, columnspan=2, sticky="ew",
                                                                       pady=2, padx=(6, 0))
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        self.btn_start = ttk.Button(row, text="▶  Grab serials", style="Accent.TButton", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.pb = ttk.Progressbar(c, mode="determinate")
        self.pb.pack(fill="x", pady=(8, 0))
        self.lbl_prog = ttk.Label(c, text="Idle", style="Muted.TLabel")
        self.lbl_prog.pack(anchor="w", pady=(2, 0))
        scan_outer.pack(side="bottom", fill="x", pady=(8, 0))
        cucm_outer.pack(side="bottom", fill="x", pady=(8, 0))
        tgt_outer.pack(side="top", fill="both", expand=True)
        self._targets_changed()

    def _build_right(self, parent):
        _o, c = self._card(parent, None, fill="both", expand=True, padx=(8, 0))
        top = ttk.Frame(c, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Results", style="H.TLabel").pack(side="left")
        self.lbl_stats = ttk.Label(top, text="", style="Stat.TLabel")
        self.lbl_stats.pack(side="left", padx=16)
        self.v_only_ok = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Phones only", variable=self.v_only_ok, style="Card.TCheckbutton",
                        command=self.refresh_tree).pack(side="right")
        self.v_filter = tk.StringVar()
        self.v_filter.trace_add("write", lambda *_: self.refresh_tree())
        ttk.Entry(top, textvariable=self.v_filter, width=24).pack(side="right", padx=(4, 12))
        ttk.Label(top, text="Filter", style="Muted.TLabel").pack(side="right")

        fr = ttk.Frame(c, style="Card.TFrame")
        fr.pack(fill="both", expand=True)
        cols = [k for k, _h, _w in E.COLUMNS]
        self.tv = ttk.Treeview(fr, columns=cols, show="headings", selectmode="extended")
        for k, h, w in E.COLUMNS:
            self.tv.heading(k, text=h, command=lambda k=k: self.sort_by(k))
            self.tv.column(k, width=w, anchor="w", stretch=(k == "note"))
        ys = ttk.Scrollbar(fr, orient="vertical", command=self.tv.yview)
        xs = ttk.Scrollbar(fr, orient="horizontal", command=self.tv.xview)
        self.tv.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tv.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        fr.rowconfigure(0, weight=1)
        fr.columnconfigure(0, weight=1)
        self.tv.tag_configure("odd", background=C["stripe"])
        self.tv.tag_configure("ok", foreground=C["ink"])
        self.tv.tag_configure("partial", foreground=C["warn"])
        self.tv.tag_configure("bad", foreground=C["err"])
        self.tv.tag_configure("dim", foreground=C["muted"])
        self.tv.bind("<Control-c>", lambda e: self.copy_rows())
        self.tv.bind("<Button-3>", self._menu)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Copy selected rows", command=self.copy_rows)
        self.menu.add_command(label="Copy serial", command=lambda: self.copy_field("serial"))
        self.menu.add_command(label="Copy MAC", command=lambda: self.copy_field("mac"))
        self.menu.add_separator()
        self.menu.add_command(label="Open phone web page", command=self.open_web)
        self.menu.add_command(label="Re-scan selected", command=self.rescan_selected)

    # ------------------------------------------------------------------------------------------- targets
    def _targets_changed(self, _e=None):
        self.t_targets.edit_modified(False)
        if hasattr(self, "_tc_job"):
            self.after_cancel(self._tc_job)
        self._tc_job = self.after(300, self._count_targets)

    def _count_targets(self):
        t, errs = E.parse_targets(self.t_targets.get("1.0", "end"))
        txt = f"{len(t):,} address{'es' if len(t) != 1 else ''}"
        if errs:
            txt += f"  ·  {len(errs)} invalid"
        self.lbl_count.configure(text=txt, foreground=C["err"] if errs else C["muted"])

    def load_file(self):
        p = filedialog.askopenfilename(title="Load targets", filetypes=[
            ("Target lists", "*.txt *.csv *.xlsx *.xlsm"), ("All files", "*.*")])
        if not p:
            return
        try:
            txt = E.read_target_file(p)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Could not read {p}:\n{e}")
            return
        if not txt.strip():
            messagebox.showwarning(APP_TITLE, "No IP addresses, ranges or subnets found in that file.")
            return
        self._append_targets(txt)

    def _append_targets(self, txt):
        cur = self.t_targets.get("1.0", "end").strip()
        self.t_targets.delete("1.0", "end")
        self.t_targets.insert("1.0", (cur + "\n" if cur else "") + txt.strip() + "\n")
        self._targets_changed()

    def clear_targets(self):
        self.t_targets.delete("1.0", "end")
        self.extra = {}
        self._targets_changed()

    # ------------------------------------------------------------------------------------------- CUCM
    def discover(self):
        host, user, pw = self.v_host.get().strip(), self.v_user.get().strip(), self.v_pw.get()
        if not (host and user and pw):
            messagebox.showwarning(APP_TITLE, "Enter the CUCM node, user and password.")
            return
        if self.busy:
            return
        self._set_busy(True, f"Asking {host} for phones…")
        status = self.v_cstatus.get()

        def run():
            try:
                devs = E.cucm_discover(host, user, pw, status=status,
                                       log=lambda m: self.q.put(("log", m)))
                self.q.put(("cucm", devs))
            except Exception as e:
                self.q.put(("cucm_err", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _cucm_done(self, devs):
        self._set_busy(False)
        ips, no_ip, web_off = [], 0, 0
        for d in devs:
            if not d["ip"]:
                no_ip += 1
                continue
            ips.append(d["ip"])
            self.extra[d["ip"]] = {"hostname": d["name"], "dn": d["dn"], "cucm_desc": d["desc"],
                                   "cucm_status": d["status"]}
            if d.get("httpd", "").lower() == "no":
                web_off += 1
        if ips:
            self._append_targets("\n".join(ips))
        msg = f"CUCM returned {len(devs)} phones; {len(ips)} IPs added to the target list."
        if no_ip:
            msg += f"\n{no_ip} had no IP address (unregistered / never registered)."
        if web_off:
            msg += f"\n{web_off} report their web server as disabled — enable 'Web Access' on those phones."
        self.lbl_prog.configure(text=msg.split("\n")[0])
        messagebox.showinfo(APP_TITLE, msg)

    # ------------------------------------------------------------------------------------------- scan
    def _opts(self):
        try:
            workers = max(1, min(256, int(self.v_workers.get())))
            timeout = max(0.5, min(60.0, float(self.v_timeout.get())))
        except ValueError:
            raise ValueError("Parallel and timeout must be numbers.")
        auth = (self.v_puser.get().strip(), self.v_ppw.get()) if self.v_puser.get().strip() else None
        return workers, timeout, auth

    def start(self, targets=None):
        if self.busy:
            return
        if targets is None:
            targets, errs = E.parse_targets(self.t_targets.get("1.0", "end"))
            if errs:
                more = "\n".join(errs[:10]) + ("\n…" if len(errs) > 10 else "")
                if not messagebox.askyesno(APP_TITLE, f"These entries are not valid and will be skipped:\n\n{more}"
                                                      f"\n\nContinue with {len(targets)} addresses?"):
                    return
            if not targets:
                messagebox.showwarning(APP_TITLE, "Add some IP addresses, ranges or subnets first.")
                return
        try:
            workers, timeout, auth = self._opts()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        self._save()
        # replace earlier results for the same IPs, keep the rest
        tset = set(targets)
        self.results = [r for r in self.results if r["ip"] not in tset]
        self.refresh_tree()
        self.stop_event.clear()
        self.pb.configure(maximum=len(targets), value=0)
        self._set_busy(True, f"Scanning {len(targets):,} addresses…")
        https, extra = self.v_https.get(), dict(self.extra)

        def run():
            try:
                E.scan(targets, workers=workers, timeout=timeout, try_https=https, auth=auth,
                       stop_event=self.stop_event, extra=extra,
                       on_result=lambda r, d, t: self.q.put(("res", (r, d, t))))
            except Exception as e:
                self.q.put(("log", f"Scan failed: {e}"))
            self.q.put(("done", None))

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.lbl_prog.configure(text="Stopping — finishing requests already in flight…")

    def _set_busy(self, busy, msg=None):
        self.busy = busy
        self.btn_start.configure(state="disabled" if busy else "normal")
        self.btn_cucm.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if msg:
            self.lbl_prog.configure(text=msg)

    def _drain(self):
        new_rows = False
        try:
            for _ in range(2000):
                kind, data = self.q.get_nowait()
                if kind == "res":
                    r, done, total = data
                    self.results.append(r)
                    new_rows = True
                    self.pb.configure(value=done)
                    self.lbl_prog.configure(text=f"{done:,} / {total:,}   ·   last: {r['ip']}  {r['status']}")
                elif kind == "done":
                    new_rows = True
                    self._set_busy(False)
                    ok = sum(1 for r in self.results if r["status"] == E.ST_OK)
                    self.lbl_prog.configure(text=("Stopped" if self.stop_event.is_set() else "Finished") +
                                            f"  ·  {ok} serial numbers read")
                elif kind == "log":
                    self.lbl_prog.configure(text=data)
                elif kind == "cucm":
                    self._cucm_done(data)
                elif kind == "cucm_err":
                    self._set_busy(False, "CUCM discovery failed")
                    messagebox.showerror(APP_TITLE, data)
        except queue.Empty:
            pass
        if new_rows:
            self.refresh_tree()
        self.after(150, self._drain)

    # ------------------------------------------------------------------------------------------- results
    def _visible(self):
        f = self.v_filter.get().strip().lower()
        rows = self.results
        if self.v_only_ok.get():
            rows = [r for r in rows if r["status"] in (E.ST_OK, E.ST_PARTIAL)]
        if f:
            rows = [r for r in rows if any(f in str(r.get(k, "")).lower() for k, _h, _w in E.COLUMNS)]
        if self.sort_col:
            k = self.sort_col
            if k == "ip":
                rows = sorted(rows, key=_ip_key, reverse=self.sort_rev)
            else:
                rows = sorted(rows, key=lambda r: str(r.get(k, "")).lower(), reverse=self.sort_rev)
        else:
            rows = sorted(rows, key=lambda r: ({E.ST_OK: 0, E.ST_PARTIAL: 1}.get(r["status"], 2), _ip_key(r)))
        return rows

    def refresh_tree(self):
        self.tv.delete(*self.tv.get_children())
        self._row_map = {}
        for i, r in enumerate(self._visible()):
            st = r.get("status")
            tag = {E.ST_OK: "ok", E.ST_PARTIAL: "partial", E.ST_NOWEB: "bad", E.ST_ERROR: "bad"}.get(st, "dim")
            iid = self.tv.insert("", "end", values=[r.get(k, "") for k, _h, _w in E.COLUMNS],
                                 tags=(tag, "odd") if i % 2 else (tag,))
            self._row_map[iid] = r
        counts = {}
        for r in self.results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        models = len({r.get("model") for r in self.results if r["status"] == E.ST_OK and r.get("model")})
        parts = [f"{counts.get(E.ST_OK, 0)} serials", f"{models} models"]
        for st in (E.ST_PARTIAL, E.ST_NOWEB, E.ST_NOTPHONE, E.ST_DOWN, E.ST_ERROR):
            if counts.get(st):
                parts.append(f"{counts[st]} {st.lower()}")
        self.lbl_stats.configure(text="   ·   ".join(parts) if self.results else "")

    def sort_by(self, k):
        self.sort_rev = (not self.sort_rev) if self.sort_col == k else False
        self.sort_col = k
        self.refresh_tree()

    def _selected(self):
        return [self._row_map[i] for i in self.tv.selection() if i in self._row_map]

    def _menu(self, e):
        iid = self.tv.identify_row(e.y)
        if iid and iid not in self.tv.selection():
            self.tv.selection_set(iid)
        if self.tv.selection():
            self.menu.tk_popup(e.x_root, e.y_root)

    def _clip(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def copy_rows(self):
        rows = self._selected()
        if rows:
            lines = ["\t".join(h for _k, h, _w in E.COLUMNS)]
            lines += ["\t".join(str(r.get(k, "")) for k, _h, _w in E.COLUMNS) for r in rows]
            self._clip("\n".join(lines))

    def copy_field(self, k):
        vals = [str(r.get(k, "")) for r in self._selected() if r.get(k)]
        if vals:
            self._clip("\n".join(vals))

    def copy_serials(self):
        rows = [r for r in self._visible() if r.get("serial")]
        if not rows:
            messagebox.showinfo(APP_TITLE, "No serial numbers to copy yet.")
            return
        self._clip("\n".join(f"{r['serial']}\t{r.get('model', '')}\t{r.get('mac', '')}\t{r['ip']}" for r in rows))
        self.lbl_prog.configure(text=f"Copied {len(rows)} serials (serial, model, MAC, IP — tab separated)")

    def open_web(self):
        import webbrowser
        for r in self._selected()[:5]:
            scheme = "https" if r.get("source", "").startswith("https") else "http"
            webbrowser.open(f"{scheme}://{r['ip']}/")

    def rescan_selected(self):
        ips = [r["ip"] for r in self._selected()]
        if ips:
            self.start(ips)

    def clear_results(self):
        if self.results and messagebox.askyesno(APP_TITLE, "Clear all results?"):
            self.results = []
            self.refresh_tree()

    def export(self, kind):
        rows = self._visible()
        if not rows:
            messagebox.showinfo(APP_TITLE, "Nothing to export yet.")
            return
        ext = ".xlsx" if kind == "xlsx" else ".csv"
        p = filedialog.asksaveasfilename(title="Export", defaultextension=ext, initialfile=f"IP_Phone_Serials{ext}",
                                         filetypes=[("Excel", "*.xlsx")] if kind == "xlsx" else [("CSV", "*.csv")])
        if not p:
            return
        try:
            (E.export_xlsx if kind == "xlsx" else E.export_csv)(rows, p)
        except PermissionError:
            messagebox.showerror(APP_TITLE, f"Cannot write {p} — is it open in Excel?")
            return
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Export failed:\n{e}")
            return
        self.lbl_prog.configure(text=f"Exported {len(rows)} rows to {os.path.basename(p)}")
        if messagebox.askyesno(APP_TITLE, f"Exported {len(rows)} rows.\n\nOpen the file now?"):
            os.startfile(p)

    # ------------------------------------------------------------------------------------------- settings
    def _save(self):
        s = self.settings
        s["targets"] = self.t_targets.get("1.0", "end").strip()[:200000]
        s["cucm_host"], s["cucm_user"] = self.v_host.get().strip(), self.v_user.get().strip()
        s["cucm_status"] = self.v_cstatus.get()
        s["phone_user"] = self.v_puser.get().strip()
        s["https"] = bool(self.v_https.get())
        try:
            s["workers"], s["timeout"] = int(self.v_workers.get()), float(self.v_timeout.get())
        except ValueError:
            pass
        save_settings(s)

    def on_close(self):
        self.stop_event.set()
        self._save()
        self.destroy()


def _ip_key(r):
    try:
        return (0, tuple(int(p) for p in r["ip"].split(".")))
    except ValueError:
        return (1, r["ip"])


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()
