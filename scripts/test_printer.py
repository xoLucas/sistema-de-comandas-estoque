#!/usr/bin/env python3
"""
Standalone printer test script for Lads Beer thermal printers.

Usage examples:
    python scripts/test_printer.py --ip 192.168.1.101
    python scripts/test_printer.py --ip 192.168.1.102 --port 9100 --width 48
    python scripts/test_printer.py --ip 192.168.1.101 --no-cut

This script does NOT require the Docker containers to be running.
It sends a raw ESC/POS test ticket directly to the printer over the network.
"""

import argparse
import socket
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


ESC = b"\x1b"
GS = b"\x1d"


def _cmd(*parts: bytes) -> bytes:
    return b"".join(parts)


def _text(text: str) -> bytes:
    try:
        return text.encode("cp850")
    except UnicodeEncodeError:
        return text.encode("ascii", errors="ignore")


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    padding = (width - len(text)) // 2
    return " " * padding + text


def _line(char: str = "-", width: int = 32) -> str:
    return char * width


def build_test_ticket(width: int = 48, cut_paper: bool = True) -> bytes:
    """Build a simple ESC/POS test ticket."""
    data = bytearray()
    data.extend(_cmd(ESC, b"@"))  # Initialize
    data.extend(_cmd(ESC, b"a", b"\x01"))  # Align center
    data.extend(_cmd(ESC, b"E", b"\x01"))  # Bold on
    data.extend(_text("LADS BEER"))
    data.extend(_cmd(ESC, b"E", b"\x00"))  # Bold off
    data.extend(_text("\n"))
    data.extend(_text("Teste de Impressora"))
    data.extend(_text("\n"))
    data.extend(_text("=" * min(width, 40)))
    data.extend(_text("\n"))

    data.extend(_cmd(ESC, b"a", b"\x00"))  # Align left
    data.extend(_text("Esta e uma impressao de teste.\n"))
    data.extend(_text("Se voce esta lendo isso, a\n"))
    data.extend(_text("impressora esta configurada\n"))
    data.extend(_text("corretamente na rede.\n"))
    data.extend(_text(_line("-", width)))
    data.extend(_text("\n"))

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    data.extend(_text(f"Data: {now.strftime('%d/%m/%Y %H:%M')}\n"))
    data.extend(_text("Porta: 9100 (raw ESC/POS)\n"))
    data.extend(_text(_line("-", width)))
    data.extend(_text("\n"))

    data.extend(_cmd(ESC, b"a", b"\x01"))  # Align center
    data.extend(_text("Sistema Lads Beer\n"))
    data.extend(_text("OK\n"))

    if cut_paper:
        data.extend(b"\n\n\n")
        data.extend(_cmd(GS, b"V", b"\x00"))  # Partial cut

    return bytes(data)


def send_to_printer(ip: str, port: int, data: bytes, timeout: int = 5) -> None:
    """Send raw ESC/POS data to a network printer."""
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.sendall(data)


def print_terminal_preview(width: int = 48) -> None:
    """Print a human-readable preview of the test ticket."""
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    print("=" * width)
    print(_center("LADS BEER", width))
    print(_center("Teste de Impressora", width))
    print("=" * width)
    print("Esta e uma impressao de teste.")
    print("Se voce esta lendo isso, a")
    print("impressora esta configurada")
    print("corretamente na rede.")
    print(_line("-", width))
    print(f"Data: {now.strftime('%d/%m/%Y %H:%M')}")
    print("Porta: 9100 (raw ESC/POS)")
    print(_line("-", width))
    print(_center("Sistema Lads Beer", width))
    print(_center("OK", width))
    print("=" * width)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envia um ticket de teste para uma impressora termica ESC/POS de rede."
    )
    parser.add_argument("--ip", required=True, help="Endereco IP da impressora")
    parser.add_argument("--port", type=int, default=9100, help="Porta da impressora (padrao 9100)")
    parser.add_argument("--width", type=int, default=48, help="Largura do ticket em colunas (padrao 48 para 80mm)")
    parser.add_argument("--no-cut", action="store_true", help="Nao enviar comando de corte no final")
    parser.add_argument("--preview", action="store_true", help="Mostra preview no terminal e nao imprime")
    parser.add_argument("--timeout", type=int, default=5, help="Timeout de conexao em segundos")
    args = parser.parse_args()

    if args.width <= 0:
        print("Erro: --width deve ser maior que zero.", file=sys.stderr)
        return 1

    data = build_test_ticket(width=args.width, cut_paper=not args.no_cut)

    print_terminal_preview(width=args.width)

    if args.preview:
        print("\n[Preview mode: nenhum dado foi enviado para a impressora]")
        return 0

    try:
        send_to_printer(args.ip, args.port, data, timeout=args.timeout)
        print(f"\n[OK] Ticket de teste enviado para {args.ip}:{args.port}")
        return 0
    except socket.timeout:
        print(f"\n[ERRO] Tempo esgotado ao conectar em {args.ip}:{args.port}", file=sys.stderr)
        print("Verifique se:", file=sys.stderr)
        print("  - A impressora esta ligada e conectada ao roteador", file=sys.stderr)
        print("  - O IP e a porta estao corretos", file=sys.stderr)
        print("  - O PC esta na mesma rede (192.168.1.x)", file=sys.stderr)
        return 1
    except ConnectionRefusedError:
        print(f"\n[ERRO] Conexao recusada em {args.ip}:{args.port}", file=sys.stderr)
        print("A impressora pode estar offline ou a porta 9100 pode estar desativada.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[ERRO] Falha ao enviar para {args.ip}:{args.port}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
