The textbook files (Pattanayak, Quantum Machine Learning with Python, Apress
2021, Listing 5.1 and the modules it imports).  Nothing in this folder has been
changed from what was supplied.

  HHL.py                     the listing itself                 (supplied as a file)
  QuantumPhaseEstimation.py  imported by HHL.py                 (supplied as a file)
  textbook_output.txt        output printed in the book         (supplied as a file)
  EigenValueInversion.py     imported by HHL.py                 (saved from pasted text)
  hamiltonian_simulator.py   imported by HHL.py                 (saved from pasted text)

If your copy of the book's code differs from the two pasted files, replace
them with your own.

These files do not run on a current Cirq.  code/textbook_replay.py runs them
unmodified through a small compatibility shim; code/hhl_cirq.py is the
repaired and extended port used in the paper.
