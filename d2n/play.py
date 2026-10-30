"""Lance NetHack en mode wizard directement sur un niveau converti.

NetHack tourne dans un pseudo-terminal.  Le joueur répond lui-même aux
questions du début de partie (personnage, tutoriel...) ; dès que la partie
commence, les touches qui mènent au niveau sont tapées à sa place, puis il
reprend la main :

- niveau simple : Ctrl-V 3 (téléportation au niveau 3), #wizloaddes
  <niveau>, Ctrl-F (carte révélée) ;
- branche : Ctrl-V ?, choix du premier niveau de la branche dans le menu,
  Ctrl-F.

Les invites sont reconnues en anglais et en français.

    python3 -m d2n.play [--branch] NIVEAU
"""

import codecs
import fcntl
import os
import pty
import re
import select
import signal
import sys
import termios
import time
import tty

ANSI = re.compile(r"\x1b(\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*\x07|[()][0-9A-Z]|.)"
                  r"|[\x00-\x08\x0e-\x1f]")
STATUS = re.compile(r"(Dlvl|Niv):\s*\d")
MORE = re.compile(r"--(More|Plus)--")
# Menu ou question qui attend une réponse du joueur.
PENDING = re.compile(r"\((end|fin|\d+ (of|sur) \d+)\)|\[[yn][ynaq#]*\]")
TELEPORT = re.compile(r"teleport|téléport", re.I)
LOADDES = re.compile(r"\blua\b", re.I)
PAGE = re.compile(r"\((\d+) (?:of|sur) (\d+)\)")

CTRL_F, CTRL_V = "\x06", "\x16"


class Game:
    """NetHack dans un pseudo-terminal, affiché dans le terminal courant."""

    def __init__(self, argv, env, out=None):
        self.out = sys.stdout.fileno() if out is None else out
        self.pid, self.fd = pty.fork()
        if self.pid == 0:                           # processus fils
            try:
                os.execvpe(argv[0], argv, env)
            finally:
                os._exit(127)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.since = ""         # sortie depuis la dernière touche envoyée
        self.status = False     # ligne d'état vue : la partie a commencé
        self.last_out = time.time()
        self.alive = True
        self.resize()

    def resize(self, *_):
        try:
            size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ,
                               b"\0" * 8)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    def text(self):
        return ANSI.sub("", self.since)

    def pump(self, timeout, forward):
        """Recopie la sortie de NetHack à l'écran ; transmet le clavier si
        `forward` (sinon il est ignoré)."""
        stdin = sys.stdin.fileno()
        fds = [self.fd, stdin] if forward else [self.fd]
        try:
            r, _, _ = select.select(fds, [], [], timeout)
        except InterruptedError:
            return
        if self.fd in r:
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            if not data:
                self.alive = False
                return
            os.write(self.out, data)
            self.since += self.decoder.decode(data)
            self.since = self.since[-200000:]
            self.status = self.status or bool(STATUS.search(self.text()))
            self.last_out = time.time()
        if stdin in r:
            data = os.read(stdin, 1024)
            if forward and data:
                self.write(data.decode("utf-8", "replace"))

    def write(self, keys):
        self.log(f"<<< {self.text()[-300:]!r}\n>>> {keys!r}")
        os.write(self.fd, keys.encode())
        self.since = ""
        self.last_out = time.time()     # attendre la réponse avant settle()

    def log(self, text):
        """Journal de débogage (variable D2N_PLAY_LOG)."""
        path = os.environ.get("D2N_PLAY_LOG")
        if path:
            with open(path, "a") as f:
                f.write(text + "\n")

    def quiet(self, delay):
        return time.time() - self.last_out >= delay

    def wait(self, cond, timeout=8.0, forward=False):
        end = time.time() + timeout
        while self.alive and time.time() < end:
            if cond():
                return True
            self.pump(0.05, forward)
        return False

    def settle(self, delay=0.4):
        """Attend la fin de l'affichage, en fermant les --More--."""
        while self.wait(lambda: self.quiet(delay)):
            if not MORE.search(self.text()):
                return True
            self.write("\r")
        return False

    def wait_start(self):
        """Laisse le joueur répondre aux questions du début de partie,
        jusqu'à ce que la carte soit affichée sans question en attente."""
        while self.alive:
            self.pump(0.05, True)
            if not self.status or not self.quiet(0.6):
                continue
            text = self.text()
            if MORE.search(text):
                self.write("\r")
            elif not PENDING.search(text):
                return True
        return False

    def interact(self):
        while self.alive:
            self.pump(1.0, True)

    def close(self):
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


def goto_level(game, name):
    """Niveau simple : téléportation au niveau 3, puis #wizloaddes."""
    game.write(CTRL_V)
    if not game.wait(lambda: TELEPORT.search(game.text())):
        return "pas d'invite de téléportation"
    game.write("3\r")
    game.settle()
    game.write("#")
    game.settle(0.2)
    game.write("wizloaddes")
    game.settle(0.2)
    game.write("\r")
    if not game.wait(lambda: LOADDES.search(game.text())):
        return "pas d'invite de #wizloaddes"
    game.write(name + "\r")
    game.settle()
    return None


def goto_branch(game, first):
    """Branche : menu de téléportation de Ctrl-V, niveau `first`."""
    game.write(CTRL_V)
    if not game.wait(lambda: TELEPORT.search(game.text())):
        return "pas d'invite de téléportation"
    game.write("?\r")
    entry = re.compile(rf"\b([a-zA-Z]) - [ *]*{re.escape(first)}\s*:")
    for _ in range(10):
        game.settle()
        text = game.text()
        m = entry.search(text)
        if m:
            game.write(m.group(1))
            game.settle()
            return None
        page = PAGE.findall(text)
        if not page or int(page[-1][0]) >= int(page[-1][1]):
            break
        game.write(">")
    game.write("\x1b")
    game.settle()
    return f"{first} absent du menu de téléportation (branche non déclarée ?)"


def play(nethack, hackdir, name, branch=False):
    """Joue le niveau `name` (premier niveau de la branche si `branch`).
    Retourne None, ou la raison pour laquelle le niveau n'a pas pu être
    atteint (le joueur garde alors la main sur la partie)."""
    if not sys.stdin.isatty():
        return "un terminal est nécessaire"
    env = dict(os.environ, HACKDIR=hackdir)
    saved = termios.tcgetattr(sys.stdin.fileno())
    game = Game([nethack, "-D"], env)
    old = signal.signal(signal.SIGWINCH, game.resize)
    error = None
    try:
        tty.setraw(sys.stdin.fileno())
        if not game.wait_start():
            return "NetHack s'est arrêté avant le début de la partie"
        error = (goto_branch if branch else goto_level)(game, name)
        if error is None:
            game.write(CTRL_F)
            game.settle()
        game.interact()
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
        signal.signal(signal.SIGWINCH, old)
        game.close()
    return error


def main(argv):
    from .tui import HACKDIR, NETHACK
    branch = "--branch" in argv
    args = [a for a in argv if a != "--branch"]
    if len(args) != 1:
        raise SystemExit(__doc__.rsplit("\n\n", 1)[-1])
    error = play(NETHACK, HACKDIR, args[0], branch)
    if error:
        print(f"doom2nethack : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
