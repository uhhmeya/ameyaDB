# HHL in Cirq and Qiskit

Homework project: the HHL algorithm for linear systems, implemented in Cirq
(starting from Listing 5.1 of Pattanayak's textbook) and in Qiskit, with four
experiments and a paper in the ACM template.

## What is where

| Folder | Contents |
|---|---|
| `paper/` | The paper. `main.tex` is the source, `main.pdf` the compiled result. The folder is self-contained: upload it to Overleaf as it is. `tables/`, `results_macros.tex`, `code/` and most of `figures/` are generated, so do not edit them by hand. `figures/src/` holds the two hand-drawn TikZ figures. |
| `code/hhl_common.py` | The four linear systems, the choice of `t` and `C`, the rotation-angle table and the decoding of measurement counts. No quantum library. |
| `code/hhl_cirq.py` | Cirq implementation, ported from the textbook listing. It has no comments; Table 2 of the paper lists what was changed. |
| `code/hhl_qiskit.py` | Qiskit implementation, written from scratch with AI help (declared on its first line). |
| `code/run_experiments.py` | Runs everything on both frameworks and writes `results/results.json`. |
| `code/make_paper_assets.py` | Turns `results.json` into the figures, tables and numbers of the paper. |
| `code/textbook_replay.py` | Runs the original textbook files, unmodified, on a current Cirq. |
| `code/test_hhl.py` | Automated checks (`pytest`). |
| `textbook_listing/` | The textbook files exactly as given. |
| `results/` | `results.json` and PNG previews of the figures. |

## Run it

```bash
pip install -r requirements.txt
cd code
pytest -q                     # all checks should pass
python run_experiments.py     # about half a minute
python make_paper_assets.py   # figures, tables, numbers -> ../paper
```

Then compile the paper, either on Overleaf (upload the `paper` folder, main
document `main.tex`, compiler pdfLaTeX) or locally:

```bash
cd ../paper
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

## Change it

Every number, table and figure in the paper is generated. To use your own
linear system, edit `SYSTEMS` in `code/hhl_common.py`, re-run the two scripts
above and recompile. Sentences that describe a specific system in words
(Sections 3.1, 3.4 and 5.3 to 5.5 of the paper) have to be updated by hand.

The matrix must be real symmetric (or Hermitian) and positive definite, and
its size must be a power of two (use `pad_to_power_of_two` otherwise). For the
automatic choice of `C` every diagonal entry must be larger than the sum of the
absolute values of the other entries in its row; otherwise pass your own
`bounds=(lower, upper)`.

## AI assistance

The code and the first draft of the paper were produced with the help of an AI
assistant (Claude, Anthropic). The paper's acknowledgments say so; keep that
statement accurate if you change how the work was done.
