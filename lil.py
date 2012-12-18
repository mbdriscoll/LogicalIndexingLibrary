import sys, re, ast, z3

# Pattern for parsing layout declarations
pattern = re.compile('(?P<layout>\w+)\((?P<dim0>[^,]+), *(?P<dim1>[^,]+), *(?P<rest>.*)\)')

class Z3Rewriter(ast.NodeTransformer):
    """
    Convert all variables and numbers in a Python AST to Z3 elements.
    """
    def visit_Name(self, node):
        """ Convert variables: foo -> z3.BitVec('foo', 32) """
        return ast.copy_location(
          ast.Call(
            func=ast.Attribute(value=ast.Name(id='z3', ctx=ast.Load()),
                               attr='BitVec', ctx=ast.Load()),
            args=[ast.Str(s=node.id), ast.Num(n=32)],
            keywords=[]), node)
    def visit_Num(self, node):
        """ Convert numbers: 1337 -> z3.BitVecVal(1337, 32) """
        return ast.copy_location(
          ast.Call(
            func=ast.Attribute(value=ast.Name(id='z3', ctx=ast.Load()),
                               attr='BitVecVal', ctx=ast.Load()),
            args=[ast.Num(n=node.n), ast.Num(n=32)],
            keywords=[]), node)


def parse_expr(e):
    """
    Given a python expression convertible to a string, parse it, replace
    its variables and values with z3 bitvecs, and return its AST.
    """
    input_ast = ast.parse(str(e), mode='eval')
    z3_ast = Z3Rewriter().visit(input_ast)
    ast.copy_location(z3_ast, input_ast)
    ast.fix_missing_locations(z3_ast)
    z3_code = compile(z3_ast, filename='<unknown>', mode='eval')
    return eval(z3_code)
E = parse_expr

class LayoutDecl(object):
    """
    Abstract class to describe a single-level layout declaration. Concrete layouts
    like Row-Major, Column-Major, Z-Morton, and Hilbert derive from this.
    """
    def __init__(self, matchobj):
        for key in matchobj.groupdict():
            if key not in ['layout', 'rest']:
                setattr(self, key, parse_expr(matchobj.groupdict()[key]))
        rest = matchobj.groupdict()['rest']
        if re.match(pattern, rest):
            self.rest = LayoutDeclFactory(rest)
        else:
            assert rest == str(1), \
                "For now, inner-most element must have size 1, not '%s'" % rest
            self.rest = parse_expr(rest)

    def size(self):
        """ The total number of elements in this layout. """
        val = self.dim0 * self.dim1
        if not self.terminal():
            val *= self.rest.size()
        return val

    def elem_size(self):
        """ The size of the element in this layout """
        return self.rest if self.terminal() else self.rest.size()

    def terminal(self):
        """ True iff this is the innermost layout declaration. """
        return not isinstance(self.rest, LayoutDecl)

    def ldim0(self):
        """ The logical size along dimension 0. """
        val = self.dim0
        if not self.terminal():
            val *= self.rest.ldim0()
        return val

    def ldim1(self):
        """ The logical size along dimension 1. """
        val = self.dim1
        if not self.terminal():
            val *= self.rest.ldim1()
        return val

    def lsize0(self):
        """ The logical element size along dimension 0. """
        return self.rest if self.terminal() else self.rest.ldim0()

    def lsize1(self):
        """ The logical element size along dimension 1. """
        return self.rest if self.terminal() else self.rest.ldim1()

    def interpret(self, i, j):
        """ Convert logical indices i and j into a physical index. """
        Bx = i / self.lsize0()
        By = j / self.lsize1()
        p = self.fragment(Bx, By)
        if not self.terminal():
            x = i % self.lsize0()
            y = j % self.lsize1()
            p *= self.elem_size()
            p += self.rest.interpret(x, y)
        return z3.simplify(p)


"""
Concrete classes for supported layouts.
"""
class RowMajLayoutDecl(LayoutDecl):
    name = "ROWMAJ"
    def fragment(self, i, j):
        return i*self.dim1 + j

class ColMajLayoutDecl(LayoutDecl):
    name = "COLMAJ"
    def fragment(self, i, j):
        return i + self.dim0*j

class ZMortonLayoutDecl(LayoutDecl):
    name = "ZMORTON"
    def fragment(self, i, j):
        return interleave_bits(i,j)

class HilbertLayoutDecl(LayoutDecl):
    # from http://stackoverflow.com/a/313964, with r=16
    name = "HILBERT"
    def fragment(self, i, j):
        heven = i ^ j
        noti = ~i & E(0x0000FFFF)
        notj = ~j & E(0x0000FFFF)
        temp = noti ^ j
        v0, v1 = E(0), E(0)
        for k in range(1, 16):
            v1 = ((v1 & heven) | ((v0 ^ notj) & temp)) >> E(1)
            v0 = ((v0 & (v1 ^ noti)) | (~v0 & (v1 ^ notj))) >> E(1)
        hodd = (~v0 & (v1 ^ i)) | (v0 & (v1 ^ notj))
        return interleave_bits(hodd, heven)


def interleave_bits(i, j):
    """ Helper method that interleaves the bits of indices i and j. """
    # from http://graphics.stanford.edu/~seander/bithacks.html#InterleaveBMN
    def _shiftmask(n, s, v):
        return v & ((n << s) | n)
    def _spreadbits(i):
        tmp = _shiftmask(i & 0x0000FFFF, 2, 0x33333333)
        return _shiftmask(tmp, 1, 0x55555555)
    return _spreadbits(j) | (_spreadbits(i) << 1)


def LayoutDeclFactory(text):
    """ Parse text and return the corresponding LayoutDecl subclass. """
    mo = pattern.search(text)
    layout = mo.groupdict()['layout']
    if RowMajLayoutDecl.name.startswith(layout):
        decl = RowMajLayoutDecl(mo)
    elif ColMajLayoutDecl.name.startswith(layout):
        decl = ColMajLayoutDecl(mo)
    elif ZMortonLayoutDecl.name.startswith(layout):
        decl = ZMortonLayoutDecl(mo)
    elif HilbertLayoutDecl.name.startswith(layout):
        decl = HilbertLayoutDecl(mo)
    else:
        raise Exception("Unknown layout: %s" % layout)
    return decl

def main(argv):
    """
    An example main method: parses a declaration and evaluates it at
    both concrete indices and symbolic indicies.
    """
    assert len(argv) == 2, "Usage: %s 'Z(4,4,1)'" % argv[0]

    # parse layout declaration from argv[1]
    decl = LayoutDeclFactory( argv[1] )

    # Example 1 (concrete): evaluate at (3,7)
    i, j = parse_expr(3), parse_expr(7)
    val = decl.interpret(i,j)
    print "Concrete args:\tf(%s, %s) = %s" % (i, j, val)

    # Example 2 (symbolic): evaluate at (i,j)
    i, j = parse_expr('i'), parse_expr('j')
    expression = decl.interpret(i,j)
    print "Symbolic args:\tf(%s, %s) = %s" % (i, j, expression)

    # Example 3 (mixed): evaluate at (i*3,j)
    i, j = parse_expr('i*3'), parse_expr('j+m')
    expression = decl.interpret(i,j)
    print "Mixed args:\tf(%s, %s) = %s" % (i, j, expression)

if __name__ == '__main__':
    main(sys.argv)
