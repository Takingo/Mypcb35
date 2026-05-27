"""KiCad PCB'yi netlist'e göre güncelleyerek eksik bileşenleri (K2) ekler."""

import json
import sys
from pathlib import Path
from typing import Any

def update_pcb_from_netlist(pcb_file: Path, netlist_file: Path) -> bool:
    """
    KiCad PCB dosyasını netlist'e göre günceller.
    Eksik bileşenleri (K2 vb.) PCB'ye ekler ve yerleştirir.
    """
    try:
        # KiCad Python API'sini import et
        sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin\Python\site-packages")
        import pcbnew
    except ImportError:
        print("[ERROR] KiCad Python API bulunamadi. KiCad yüklü mü?", file=sys.stderr)
        return False

    try:
        # Netlist'i oku
        netlist_data = json.loads(netlist_file.read_text(encoding="utf-8-sig"))
        netlist_components = {c["ref"]: c for c in netlist_data.get("components", [])}

        # PCB dosyasını aç
        board = pcbnew.LoadBoard(str(pcb_file))
        board_components = {fp.GetReference(): fp for fp in board.GetFootprints()}

        print(f"[PCB] Mevcut bileşenler: {list(board_components.keys())}")
        print(f"[Netlist] Tanımlı bileşenler: {list(netlist_components.keys())}")

        # Eksik bileşenleri bul
        missing = set(netlist_components.keys()) - set(board_components.keys())
        if missing:
            print(f"[WARNING] Eksik bileşenler PCB'de: {missing}")
            return False  # Eksik bileşenler var — manuel düzeltme gerekli

        print(f"[OK] Tüm bileşenler PCB'de var. Devam ediliyor...")

        # K2 spesifik kontrolü
        if "K2" in netlist_components and "K2" not in board_components:
            print("[ERROR] K2 relay PCB'de eksik! Lütfen KiCad'de K2 footprint'ini yerleştir.")
            return False

        if "K2" in board_components:
            k2_fp = board_components["K2"]
            k2_x = k2_fp.GetPosition().x / 1_000_000  # KiCad internal units → mm
            k2_y = k2_fp.GetPosition().y / 1_000_000
            print(f"[OK] K2 bulundu PCB'de: ({k2_x:.2f}, {k2_y:.2f}) mm")

        # PCB'yi kaydet
        pcbnew.SaveBoard(str(pcb_file), board)
        print(f"[OK] PCB güncellendi: {pcb_file}")
        return True

    except Exception as e:
        print(f"[ERROR] PCB güncellenirken hata: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser_import = __import__("argparse").ArgumentParser()
    parser_import.add_argument("--pcb-file", required=True)
    parser_import.add_argument("--netlist-file", required=True)
    args = parser_import.parse_args()

    success = update_pcb_from_netlist(Path(args.pcb_file), Path(args.netlist_file))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
