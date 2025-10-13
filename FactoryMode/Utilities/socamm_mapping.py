import argparse
import re


def extract_bit_mask_gb300_bianca_socamm(log_file, socket):
    pattern = re.compile(r"SDRAM training failed for channels \(failed channels mask (0x[0-9A-Fa-f]+)\)")

    channel_map = {
        "socket_0": {
            "J3": [1, 3, 5, 7, 9, 11, 13, 15],
            "J6": [0, 2, 4, 6, 8, 10, 12, 14],
            "J5": [17, 19, 21, 23, 25, 27, 29, 31],
            "J4": [16, 18, 20, 22, 24, 26, 28, 30],
        }
    }

    with open(log_file, encoding="utf-8", errors="ignore") as file:
        for line in file:
            match = pattern.search(line)
            if match:
                hex_mask = match.group(1)
                # Convert to binary and pad to 32 bits - LSB (bit 0) represents channel 0
                bin_mask = bin(int(hex_mask, 16))[2:].zfill(32)
                # Reverse to match channel numbering (bit 0 is channel 0)
                channel_list = [i for i, bit in enumerate(reversed(bin_mask)) if bit == "1"]

                j_numbers = [
                    j for j, channels in channel_map[socket].items() if any(ch in channel_list for ch in channels)
                ]

                print(f"Extracted bit mask: {hex_mask} for {socket}")
                print(f"Channels failed: {channel_list}")
                print(f"J numbers affected: {j_numbers}")
                print(
                    f"{{{{CORE_ERROR_MSG: Extracted bit mask {hex_mask} for {socket} Channels failed-{channel_list} J numbers affected-{j_numbers}}}}}"
                )
                print("{{CORE_ERROR_CODE:150}}")
                print("{{ComponentId:SOCAMM}}")
                return j_numbers  # Return list of J numbers

    print(f"No matching log entry found for {socket}.")
    return None


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Extract bit mask from log file.")
        parser.add_argument("log_file_path", type=str, help="Path to the log file")
        parser.add_argument(
            "socket", type=str, choices=["socket_0", "socket_1"], help="Socket identifier (socket_0 or socket_1)"
        )
        parser.add_argument(
            "--product", type=str, nargs="?", default=None, help="Optional: Support gb300 Bianca socamm"
        )
        args = parser.parse_args()
        print(f"Checking SOCAMM mapping for {args.product}")
        if args.product == "gb300":
            extract_bit_mask_gb300_bianca_socamm(args.log_file_path, args.socket)
        else:
            print(f"No socamm mapping for {args.product}")
    except Exception as e:
        print(f"An error occurred: {e}")
