"""ANSI 彩色输出（零依赖）。"""


class C:
    H = '\033[95m'
    B = '\033[94m'
    G = '\033[92m'
    Y = '\033[93m'
    R = '\033[91m'
    E = '\033[0m'
    BO = '\033[1m'

    @staticmethod
    def green(s): return f"{C.G}{s}{C.E}"

    @staticmethod
    def red(s): return f"{C.R}{s}{C.E}"

    @staticmethod
    def yellow(s): return f"{C.Y}{s}{C.E}"

    @staticmethod
    def blue(s): return f"{C.B}{s}{C.E}"

    @staticmethod
    def bold(s): return f"{C.BO}{s}{C.E}"

    @staticmethod
    def ok(s): return f"{C.G}[OK]{C.E} {s}"

    @staticmethod
    def fail(s): return f"{C.R}[FAIL]{C.E} {s}"

    @staticmethod
    def warn(s): return f"{C.Y}[WARN]{C.E} {s}"
