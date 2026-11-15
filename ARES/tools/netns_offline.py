"""Run a command with NO network except loopback (Linux network namespace). Usage: unshare -n python netns_offline.py cmd..."""
import fcntl, os, socket, struct, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ifr = struct.pack("16sH14s", b"lo", 0, b"")
flags = struct.unpack("16sH14s", fcntl.ioctl(s, 0x8913, ifr))[1]          # SIOCGIFFLAGS
fcntl.ioctl(s, 0x8914, struct.pack("16sH14s", b"lo", flags | 0x1, b""))   # SIOCSIFFLAGS |= IFF_UP
os.execvp(sys.argv[1], sys.argv[1:])
