"""
Hand every existing wallet the same number of spins.

Written to raise the opening balance after people had already started playing.
Setting balances flat would have been wrong twice over: it erases what anyone
has spent, and it quietly gifts back whatever is currently staked in an open
fixture, since a stake has already left the wallet and only returns at
settlement. Crediting the difference leaves both intact.

    python scripts/grant_spins.py --each 4500          # dry run, the default
    python scripts/grant_spins.py --each 4500 --yes

Only touches wallets that already exist. Anyone who hasn't got one opens at
betting.START_SPINS the first time they touch the system, so they need nothing.

Behind a TLS-intercepting proxy, also set REQUESTS_CA_BUNDLE=vmock-ca.crt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import betting
import kv


def main(argv):
    if not kv.kv_available():
        sys.exit("No KV configured. Set KV_REST_API_URL and KV_REST_API_TOKEN.")
    if "--each" not in argv:
        sys.exit(__doc__.strip())
    try:
        each = int(argv[argv.index("--each") + 1])
    except (IndexError, ValueError):
        sys.exit("--each takes a whole number of spins.")

    held = betting.balances()
    if not held:
        print("No wallets yet — nothing to top up. New players open at "
              f"{betting.START_SPINS}.")
        return 0

    staked = {}
    for pot in betting.pools_for([r["id"] for r in betting.live()]).values():
        for uid, (_, amount) in pot["bets"].items():
            staked[uid] = staked.get(uid, 0) + amount

    print(f"{len(held)} wallets, {each:+} spins each "
          f"(new opening balance is {betting.START_SPINS}):\n")
    for uid, balance in sorted(held.items(), key=lambda i: -i[1]):
        note = f"   ({staked[uid]} staked, untouched)" if uid in staked else ""
        print(f"  {uid}  {balance:>6} → {balance + each:>6}{note}")

    if "--yes" not in argv:
        print("\nDry run. Nothing changed. Re-run with --yes.")
        return 0
    betting.adjust_many([(uid, each, "opening balance raised") for uid in held])
    print(f"\nTopped up {len(held)} wallets. Anything staked in an open fixture "
          "still settles as it was.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
