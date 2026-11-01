# Custody and freeze-and-hash procedure

Applies to the held-out families CA-SCENARIO-008, 009 and 010. Tool: `tools/heldout/heldout_kit.py` (Python 3.13 standard library; run with `python -I`). The kit never deletes or overwrites a record.

## Custody rules

1. **Truth never enters a shared repository or its history.** `commit-truth` refuses truth or salt paths inside any Git work tree, and `freeze --role fixtures` refuses fixture directories inside one or containing a `truth` path component.
2. **Two independent truth copies.** The author and the reviewer each keep their own copy of `ground-truth.json` and its 32-byte salt on separately controlled storage. Before sealing, the reviewer runs `open-truth` on their copy to confirm it matches the author's commitment.
3. **Salted commitments only.** Only the salted commitment is published. An unsalted digest of a small JSON answer can be guessed by enumerating likely answers, so the plain SHA-256 of the truth is revealed only at scoring.
4. **Fixtures are confidential until the seal is public**, then go only to the executor. Metadata is public and contains no expected answers: `seal` accepts only the fields of the `eval-metadata.json` template, exactly one file in the metadata directory, and safe identifiers (`[A-Za-z0-9][A-Za-z0-9_-]{0,63}`) for scenario, fixture and variant IDs. Every sealed variant must have a sealed `variants/<ID>.json`. Tooling cannot judge free text, so a person other than the author reviews the whole public file, including `notes`, before it is frozen and records that in `prepublication_review`.
5. **Order is enforced by publication.** The seal is published before execution, and the predictions record before any truth is released to the scoring step. Publish each by an authorized commit to an evaluation branch or an issue attachment; the timestamp is the custody evidence.
6. **No changes after the seal.** The engine, scorer, kit, fixtures, truth, metadata and reporting rules stay as sealed. A defect discovered later is reported under [evaluation-process.md](evaluation-process.md#defects-found-after-sealing); a corrected version is a new family version with a new seal and a new run, and both runs are reported.
7. **Exposure retires the family.** Once results are published, or if fixtures or truth leak early, the family is no longer held out. Future generalization claims need new families.

## <a id="freeze-and-hash-procedure"></a>Freeze-and-hash procedure

Run from a checkout of the kit branch. Paths below are examples. `<WS>` is the author's private workspace and `<PUB>` is the public seal directory; both are outside any Git work tree.

1. Engine-format fixture manifest:

   ```bash
   python -I tools/heldout/heldout_kit.py manifest <WS>/CA-SCENARIO-008/fixture --fixture-id ca-scenario-008 --fixture-version 1.0.0-heldout
   ```

2. Freeze the fixtures. This hashes every file and refuses placeholders, template files, links, malformed or non-strict JSON and truth-named paths:

   ```bash
   python -I tools/heldout/heldout_kit.py freeze <WS>/CA-SCENARIO-008/fixture --role fixtures --set-id CA-SCENARIO-008 --out <PUB>/CA-SCENARIO-008/fixtures.freeze.json
   ```

3. Fill `metadata/eval-metadata.json`. Have a person other than the author review the whole file for answers or hints and complete `prepublication_review`. Copy the `metadata/` directory to `<PUB>/CA-SCENARIO-008/metadata/`, and freeze it:

   ```bash
   python -I tools/heldout/heldout_kit.py freeze <PUB>/CA-SCENARIO-008/metadata --role metadata --set-id CA-SCENARIO-008 --out <PUB>/CA-SCENARIO-008/metadata.freeze.json
   ```

4. Commit to the ground truth. The salt is written once and never overwritten:

   ```bash
   python -I tools/heldout/heldout_kit.py commit-truth <WS>/CA-SCENARIO-008/ground-truth/ground-truth.json --salt-out <WS>/CA-SCENARIO-008/ground-truth/salt.hex --out <PUB>/CA-SCENARIO-008/truth.commitment.json
   ```

5. The reviewer confirms their copy, using the commitment value from `truth.commitment.json`:

   ```bash
   python -I tools/heldout/heldout_kit.py open-truth <REVIEWER>/ground-truth.json --salt <REVIEWER>/salt.hex --commitment <hex>
   ```

6. After all three families are in `<PUB>`, seal them. The seal embeds both freeze records and the commitment for each family, re-verifies the metadata, and checks every `candidate_commit`:

   ```bash
   python -I tools/heldout/heldout_kit.py seal <PUB> --candidate c21b50dc5edd6cd07de55d2f3e0bce6103b4d952 --author "<name>" --reviewer "<name>" --out <PUB>-evaluation-seal.json
   ```

7. Publish `evaluation-seal.json` together with the `<PUB>` records. Keep `<PUB>`, private truth storage, fixture directories, the predictions directory and its record in separate, non-nested locations; `run` and `score` refuse a predictions directory inside the engine checkout or a fixture directory, a record or results file inside the predictions directory, and any existing output file. The kit commit used is recorded in the results report. Anyone can re-check a delivered fixture archive with `verify <PUB>/CA-SCENARIO-008/fixtures.freeze.json <fixture dir>`.

## Public versus private material

| Item | Visibility before scoring |
|---|---|
| `evaluation-seal.json`, freeze records, truth commitments, `eval-metadata.json` | Public |
| Fixture directories | Author, reviewer; executor only after the seal is public |
| `ground-truth.json`, salt, `scenario-spec.md` | Author and reviewer only, held separately |
| Predictions directory and record | Public once frozen |
| Results report | Public after scoring |
