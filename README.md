LogicalIndexingLibrary
======================

Generate Indexing Expressions into Arbitrarily-Nested Row-Major, Column-Major, Z-Morton, and Hilbert Layouts

Requires z3 python module.

Usage:

    $ python2.7 lil.py "ROWMAJ(8, 8, 1)"
    Concrete args:  f(3, 7) = 31
    Symbolic args:  f(i, j) = 8*i + j
    Mixed args:     f(i*3, j + m) = 24*i + j + m

argv[1] should contain a layout descriptor of the form:

    LAYOUT(n, m, k)

where:
*   LAYOUT can be ROWMAJ, COLMAJ, ZMORTON, or HILBERT,
*   n is the number of rows,
*   m is the number of columns,
*   k is the element size, or another layout descriptor.

Examples:
*   ROWMAJ(4, 4, 1) : a four-by-four block of elements in row-major order
*   ZMORTON(4, 4, 1) : a four-by-four block of elements in z-morton order
*   ZMORTON(4, 4, ROWMAJ(4, 4, 1)) : sixteen four-by-four blocks of row-major-ordered elements ordered along a Z-Morton curve.
