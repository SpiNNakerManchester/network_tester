SpiNNaker C-Application Source Files
====================================

The SpiNNaker applicatilons, written in C, which generate traffic and records
results on a SpiNNaker machine.

Compilation
-----------

The latest version of the binaries are checked into the respository (in
`network_tester/binaries/*.aplx` meaning most users will not need to build
them.  When changes are made, the binaries for each application can be rebuilt
using the associated Makefile like so:

    $ make install CFLAGS=-O3

Note that the SARK and SpiNN1 API must also be built with the -O3 optimisation
level, e.g.

    $ cd $SPINN_DIRS
    $ make clean && make CFLAGS=-O3
    $ cd -
