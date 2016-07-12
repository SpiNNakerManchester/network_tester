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

    $ make install CFLAGS="-O3"

Note that the SARK and SpiNN1 API must also be built with the -O3 optimisation
level, e.g.

    $ cd $SPINN_DIRS
    $ make clean && make APIOPT=-O3 SARKOPT=-O3
    $ cd -

The binaries will function correctly without these compilation options however
it has been found that runtime performance is inferiour preventing some
experiments from running (e.g. throughput experiments). Binaries are known to
be fast when built with -O3 and GCC 6.1.1 20160526 while some (much) older GCC
versions are known to be insufficient.
