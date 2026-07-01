"""
A minimalist, Apple-flavoured notebook TO-DO app (tkinter, no dependencies).

Design notes
------------
* The whole window is a "desk"; a spiral-bound notebook rests on it, so you are
  looking down at a real notebook laying on a surface.
* Each ruled line on the page is one task for the selected day, with an inline
  rounded checkbox sitting on the line right where the text is.
* The date control lives in the top-right corner and is fully custom-drawn.
* Selecting a different date turns the page with a short animation.
* Every keystroke and every tick is saved immediately to todo_data.json,
  kept next to this script and keyed by date.
"""

import os
import json
import math
import calendar
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, timedelta

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "todo_data.json")

# ------------------------------------------------------------------ palette
DESK_TOP     = "#c9b79f"   # warm desk, lighter at top
DESK_BOTTOM  = "#a88f72"   # darker toward the bottom (light from above)
COVER        = "#2f3742"   # notebook cover (slate)
COVER_EDGE   = "#232a33"
PAGE         = "#fdfdfb"   # paper
PAGE_EDGE    = "#e7e6df"
LINE         = "#e9e9ef"   # ruled lines
INK          = "#2b2b30"
INK_FAINT    = "#8a8a93"
DONE_INK     = "#b6b6bd"
ACCENT       = "#0a84ff"   # Apple system blue
RING         = "#c9ccd2"
RING_DARK    = "#9aa0aa"

ROW_H   = 40   # spacing between ruled lines
CB_SIZE = 20   # checkbox square


def _mix(c1, c2, t):
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class TodoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Notebook")
        self.root.geometry("760x720")
        self.root.minsize(560, 460)
        self.root.configure(bg=DESK_BOTTOM)

        self._pick_fonts()

        self.data = self._load()
        self.current = date.today()
        self.rows = []          # [{cx, cy, done, entry, tag}]
        self.overflow = []      # tasks beyond what fits on the page (preserved)
        self.hit = {}           # canvas-tag -> callback for custom "buttons"
        self._resize_job = None
        self._animating = False

        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        self.redraw_all()

    # ---------------------------------------------------------------- fonts
    def _pick_fonts(self):
        fams = set(tkfont.families())

        def pick(options):
            for o in options:
                if o in fams:
                    return o
            return options[-1]

        text_fam = pick(["SF Pro Text", "Helvetica Neue", "Segoe UI Variable",
                         "Segoe UI", "Helvetica"])
        disp_fam = pick(["SF Pro Display", "Helvetica Neue", "Segoe UI Variable",
                         "Segoe UI", "Helvetica"])
        self.f_task    = tkfont.Font(family=text_fam, size=13)
        self.f_task_d  = tkfont.Font(family=text_fam, size=13, overstrike=1)
        self.f_day     = tkfont.Font(family=disp_fam, size=26, weight="bold")
        self.f_sub     = tkfont.Font(family=text_fam, size=11)
        self.f_ui      = tkfont.Font(family=text_fam, size=11)
        self.f_ui_b    = tkfont.Font(family=text_fam, size=12, weight="bold")

    # -------------------------------------------------------------- storage
    def _load(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _collect(self):
        tasks = [{"text": r["entry"].get(), "done": r["done"]} for r in self.rows]
        tasks += self.overflow
        while tasks and tasks[-1]["text"].strip() == "" and not tasks[-1]["done"]:
            tasks.pop()
        return tasks

    def _save(self):
        key = self.current.isoformat()
        tasks = self._collect()
        if tasks:
            self.data[key] = tasks
        else:
            self.data.pop(key, None)
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print("Could not save:", e)

    # ------------------------------------------------------------- geometry
    def _geometry(self):
        W = self.canvas.winfo_width()
        H = self.canvas.winfo_height()
        pad = 26
        nb = (pad, pad, W - pad, H - pad)                       # notebook cover
        bind_w = 40
        spine = nb[0] + bind_w
        page = (spine + 8, nb[1] + 14, nb[2] - 16, nb[3] - 14)  # paper
        return {"W": W, "H": H, "nb": nb, "spine": spine, "page": page,
                "header_h": 92, "pad": pad}

    # --------------------------------------------------------------- resize
    def _on_resize(self, _evt):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(60, self.redraw_all)

    # ------------------------------------------------------------ full draw
    def redraw_all(self):
        if self._animating:
            return
        self._clear_rows()
        self.canvas.delete("all")
        self.hit.clear()
        self._draw_desk()
        self._draw_notebook()
        self._draw_contents()

    def _draw_desk(self):
        g = self._geometry()
        W, H = g["W"], g["H"]
        steps = 48
        for i in range(steps):
            y0 = H * i / steps
            y1 = H * (i + 1) / steps
            self.canvas.create_rectangle(0, y0, W, y1 + 1, width=0,
                                         fill=_mix(DESK_TOP, DESK_BOTTOM, i / steps))
        # soft vignette line near edges gives the desk a little depth
        self.canvas.create_rectangle(0, 0, W, 3, width=0, fill=_mix(DESK_TOP, "#ffffff", .25))

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _draw_notebook(self):
        g = self._geometry()
        nb = g["nb"]
        # drop shadow of the whole notebook on the desk
        self._round_rect(nb[0] + 10, nb[1] + 14, nb[2] + 12, nb[3] + 16, 22,
                         fill=_mix(DESK_BOTTOM, "#000000", .28), width=0)
        # cover
        self._round_rect(*nb, 20, fill=COVER, outline=COVER_EDGE, width=1)
        # page shadow + page
        page = g["page"]
        self._round_rect(page[0] + 4, page[1] + 6, page[2] + 6, page[3] + 8, 12,
                         fill=_mix(COVER, "#000000", .25), width=0)
        self._round_rect(*page, 12, fill=PAGE, outline=PAGE_EDGE, width=1)
        self._draw_spiral(g)

    def _draw_spiral(self, g):
        nb, spine = g["nb"], g["spine"]
        cx = (nb[0] + spine) / 2
        top, bot = nb[1] + 26, nb[3] - 26
        n = max(6, int((bot - top) // 34))
        for i in range(n + 1):
            y = top + (bot - top) * i / n
            # hole punched into the page
            self.canvas.create_oval(spine - 3, y - 5, spine + 7, y + 5,
                                    fill=_mix(PAGE, "#000000", .16), width=0)
            # metal ring across the binding
            self.canvas.create_arc(cx - 12, y - 8, cx + 16, y + 8, start=200, extent=220,
                                   style="arc", outline=RING_DARK, width=4)
            self.canvas.create_arc(cx - 12, y - 8, cx + 16, y + 8, start=205, extent=210,
                                   style="arc", outline=RING, width=2)

    # ------------------------------------------------------------- contents
    def _clear_rows(self):
        for r in self.rows:
            r["entry"].destroy()
        self.rows = []

    def _draw_contents(self):
        """Everything that changes with the selected date."""
        self._clear_rows()
        self.canvas.delete("contents")
        g = self._geometry()
        page = g["page"]

        self._draw_header(g)
        self._draw_date_control(g)

        first_line = page[1] + g["header_h"]
        capacity = max(1, int((page[3] - first_line - 8) // ROW_H))

        tasks = [dict(t) for t in self.data.get(self.current.isoformat(), [])]
        self.overflow = tasks[capacity:]
        visible = tasks[:capacity]
        while len(visible) < capacity:
            visible.append({"text": "", "done": False})

        cb_x = page[0] + 34
        text_x = page[0] + 64
        text_w = page[2] - text_x - 20

        for i, t in enumerate(visible):
            line_y = first_line + (i + 1) * ROW_H
            self.canvas.create_line(page[0] + 20, line_y, page[2] - 16, line_y,
                                    fill=LINE, tags="contents")
            cy = line_y - ROW_H / 2 + 4
            self._add_row(i, cb_x, cy, text_x, text_w, t)

    def _draw_header(self, g):
        page = g["page"]
        x = page[0] + 26
        y = page[1] + 26
        weekday = self.current.strftime("%A")
        sub = self.current.strftime("%d %B %Y").lstrip("0")
        self.canvas.create_text(x, y, text=weekday, anchor="nw",
                                fill=INK, font=self.f_day, tags="contents")
        self.canvas.create_text(x, y + 40, text=sub, anchor="nw",
                                fill=INK_FAINT, font=self.f_sub, tags="contents")
        # a hairline under the header
        self.canvas.create_line(page[0] + 20, page[1] + g["header_h"] - 6,
                                page[2] - 16, page[1] + g["header_h"] - 6,
                                fill=_mix(LINE, "#ffffff", .3), tags="contents")

    # ------------------------------------------------------- date control
    def _pill(self, x0, y0, x1, y1, tag, fill, callback, outline=""):
        item = self._round_rect(x0, y0, x1, y1, (y1 - y0) / 2,
                                fill=fill, outline=outline, width=1, tags=("contents", tag))
        self.hit[tag] = callback
        self.canvas.tag_bind(tag, "<Button-1>", lambda e, c=callback: c())
        self.canvas.tag_bind(tag, "<Enter>",
                             lambda e: self.canvas.config(cursor="hand2"))
        self.canvas.tag_bind(tag, "<Leave>",
                             lambda e: self.canvas.config(cursor=""))
        return item

    def _draw_date_control(self, g):
        page = g["page"]
        cy = page[1] + 40
        right = page[2] - 26

        # "Today" text pill
        tw = self.f_ui.measure("Today") + 28
        tx1, tx0 = right, right - tw
        self._pill(tx0, cy - 15, tx1, cy + 15, "nav_today",
                   _mix(PAGE, INK, .05), self._go_today, outline=PAGE_EDGE)
        self.canvas.create_text((tx0 + tx1) / 2, cy, text="Today", fill=INK,
                                font=self.f_ui, tags=("contents", "nav_today"))

        # date label pill with ‹  date  › arrows
        label = self.current.strftime("%a, %d %b").replace(" 0", " ")
        lw = self.f_ui_b.measure(label)
        gap = 16
        arrow = 30
        block_w = arrow + lw + 26 + arrow
        bx1 = tx0 - gap
        bx0 = bx1 - block_w
        self._round_rect(bx0, cy - 16, bx1, cy + 16, 16,
                         fill=PAGE, outline=PAGE_EDGE, width=1, tags="contents")
        # prev
        self._pill(bx0, cy - 16, bx0 + arrow + 8, cy + 16, "nav_prev",
                   "", lambda: self._shift(-1))
        self.canvas.create_text(bx0 + arrow / 2 + 4, cy, text="‹", fill=ACCENT,
                                font=self.f_day, tags=("contents", "nav_prev"))
        # next
        self._pill(bx1 - arrow - 8, cy - 16, bx1, cy + 16, "nav_next",
                   "", lambda: self._shift(1))
        self.canvas.create_text(bx1 - arrow / 2 - 4, cy, text="›", fill=ACCENT,
                                font=self.f_day, tags=("contents", "nav_next"))
        # date text (click to open calendar)
        self._pill(bx0 + arrow + 4, cy - 16, bx1 - arrow - 4, cy + 16, "nav_cal",
                   "", self._open_calendar)
        self.canvas.create_text((bx0 + bx1) / 2, cy, text=label, fill=INK,
                                font=self.f_ui_b, tags=("contents", "nav_cal"))

    # --------------------------------------------------------------- a row
    def _add_row(self, i, cb_x, cy, text_x, text_w, task):
        tag = f"cb{i}"
        rec = {"done": bool(task.get("done")), "tag": tag, "cx": cb_x, "cy": cy}

        entry = tk.Entry(self.canvas, bd=0, relief="flat", bg=PAGE,
                         fg=DONE_INK if rec["done"] else INK,
                         disabledbackground=PAGE, insertbackground=ACCENT,
                         font=self.f_task_d if rec["done"] else self.f_task,
                         highlightthickness=0)
        entry.insert(0, task.get("text", ""))
        self.canvas.create_window(text_x, cy, anchor="w", window=entry,
                                  width=text_w, height=26, tags="contents")
        entry.bind("<KeyRelease>", lambda e: self._save())
        entry.bind("<Return>", lambda e, idx=i: self._focus_next(idx))
        rec["entry"] = entry

        self.rows.append(rec)
        self._draw_checkbox(rec)
        self.canvas.tag_bind(tag, "<Button-1>", lambda e, r=rec: self._toggle(r))
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.config(cursor=""))

    def _draw_checkbox(self, rec):
        self.canvas.delete(rec["tag"])
        x, y = rec["cx"], rec["cy"]
        h = CB_SIZE / 2
        if rec["done"]:
            self._round_rect(x - h, y - h, x + h, y + h, 6, fill=ACCENT,
                             outline=ACCENT, width=1, tags=("contents", rec["tag"]))
            self.canvas.create_line(x - 5, y + 1, x - 1, y + 5, x + 6, y - 6,
                                    fill="white", width=2, capstyle="round",
                                    joinstyle="round", tags=("contents", rec["tag"]))
        else:
            self._round_rect(x - h, y - h, x + h, y + h, 6, fill=PAGE,
                             outline=_mix(INK_FAINT, "#ffffff", .3), width=1.5,
                             tags=("contents", rec["tag"]))

    def _toggle(self, rec):
        rec["done"] = not rec["done"]
        rec["entry"].configure(fg=DONE_INK if rec["done"] else INK,
                               font=self.f_task_d if rec["done"] else self.f_task)
        self._draw_checkbox(rec)
        self._save()

    def _focus_next(self, idx):
        if idx + 1 < len(self.rows):
            self.rows[idx + 1]["entry"].focus_set()

    # ------------------------------------------------------------ nav / dates
    def _shift(self, delta):
        self._change_date(self.current + timedelta(days=delta))

    def _go_today(self):
        self._change_date(date.today())

    def _change_date(self, new):
        if new == self.current or self._animating:
            return
        direction = "fwd" if new > self.current else "bwd"
        self._save()
        self.current = new
        self._animate_flip(direction, self._draw_contents)

    # -------------------------------------------------------- page turn anim
    def _animate_flip(self, direction, on_done):
        self._clear_rows()
        self.canvas.delete("contents")
        g = self._geometry()
        px0, py0, px1, py1 = g["page"]
        spine = g["spine"]
        frames = 15

        def draw_frame(k):
            self.canvas.delete("flip")
            t = k / frames
            if direction == "fwd":         # old page folds toward the spine
                edge = spine + (px1 - spine) * math.cos(t * math.pi / 2)
            else:                          # new page sweeps out from the spine
                edge = spine + (px1 - spine) * math.sin(t * math.pi / 2)
            # the turning leaf
            self._round_rect(spine, py0, edge, py1, 12, fill=PAGE,
                             outline=PAGE_EDGE, width=1, tags="flip")
            # faint ruled lines on the leaf so it reads as paper
            step = ROW_H
            yy = py0 + g["header_h"]
            while yy < py1 - 8 and edge - spine > 24:
                self.canvas.create_line(spine + 14, yy, edge - 8, yy,
                                        fill=LINE, tags="flip")
                yy += step
            # curl shadow along the free edge
            self.canvas.create_line(edge, py0 + 6, edge, py1 - 6,
                                    fill=_mix(PAGE, "#000000", .18), width=6, tags="flip")
            if k >= frames:
                self._animating = False
                self.canvas.delete("flip")
                on_done()
                return
            self.root.after(14, lambda: draw_frame(k + 1))

        self._animating = True
        draw_frame(0)

    # --------------------------------------------------------- calendar popup
    def _open_calendar(self):
        top = tk.Toplevel(self.root)
        top.title("")
        top.configure(bg=PAGE)
        top.resizable(False, False)
        top.transient(self.root)
        state = {"y": self.current.year, "m": self.current.month}

        head = tk.Frame(top, bg=PAGE)
        head.grid(row=0, column=0, columnspan=7, sticky="ew", padx=10, pady=(10, 4))
        title = tk.Label(head, bg=PAGE, fg=INK, font=self.f_ui_b)
        prevb = tk.Button(head, text="‹", bd=0, bg=PAGE, fg=ACCENT,
                          font=self.f_ui_b, activebackground=PAGE, cursor="hand2")
        nextb = tk.Button(head, text="›", bd=0, bg=PAGE, fg=ACCENT,
                          font=self.f_ui_b, activebackground=PAGE, cursor="hand2")
        prevb.pack(side="left")
        title.pack(side="left", expand=True)
        nextb.pack(side="right")

        grid = tk.Frame(top, bg=PAGE)
        grid.grid(row=1, column=0, padx=10, pady=(0, 10))

        def build():
            for w in grid.winfo_children():
                w.destroy()
            y, m = state["y"], state["m"]
            title.configure(text=date(y, m, 1).strftime("%B %Y"))
            for c, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
                tk.Label(grid, text=d, bg=PAGE, fg=INK_FAINT,
                         font=self.f_ui, width=3).grid(row=0, column=c, pady=2)
            for r, week in enumerate(calendar.Calendar().monthdayscalendar(y, m), start=1):
                for c, day in enumerate(week):
                    if day == 0:
                        continue
                    d = date(y, m, day)
                    is_today = (d == date.today())
                    is_sel = (d == self.current)
                    b = tk.Button(grid, text=str(day), width=3, bd=0, cursor="hand2",
                                  font=self.f_ui, activebackground=_mix(PAGE, ACCENT, .2),
                                  bg=ACCENT if is_sel else PAGE,
                                  fg="white" if is_sel else (ACCENT if is_today else INK),
                                  command=lambda dd=d: (top.destroy(), self._change_date(dd)))
                    b.grid(row=r, column=c, padx=1, pady=1)

        def step_month(delta):
            m = state["m"] + delta
            y = state["y"]
            if m < 1:
                m, y = 12, y - 1
            elif m > 12:
                m, y = 1, y + 1
            state["y"], state["m"] = y, m
            build()

        prevb.configure(command=lambda: step_month(-1))
        nextb.configure(command=lambda: step_month(1))
        build()

        top.update_idletasks()
        px = self.root.winfo_rootx() + self.root.winfo_width() - top.winfo_width() - 40
        py = self.root.winfo_rooty() + 90
        top.geometry(f"+{px}+{py}")


def main():
    root = tk.Tk()
    app = TodoApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app._save(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
