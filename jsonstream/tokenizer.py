#import ctypes
from cStringIO import StringIO as BytesIO

from jsonstream.yajl import lib, ffi


yajl_tok_bool, \
    yajl_tok_colon, \
    yajl_tok_comma, \
    yajl_tok_eof, \
    yajl_tok_error, \
    yajl_tok_left_bracket, \
    yajl_tok_left_brace, \
    yajl_tok_null, \
    yajl_tok_right_bracket, \
    yajl_tok_right_brace, \
    yajl_tok_integer, \
    yajl_tok_double, \
    yajl_tok_string, \
    yajl_tok_string_with_escapes, \
    yajl_tok_comment = range(15)

tokens_want_value = frozenset([
    yajl_tok_bool,
    yajl_tok_integer,
    yajl_tok_double,
    yajl_tok_string,
])


token_value_converters = {
    yajl_tok_bool: lambda x: x == 'true',
    yajl_tok_integer: int,
    yajl_tok_double: float,
    yajl_tok_string: lambda x: x.decode('utf-8'),
    yajl_tok_null: lambda x: None,
}


def _ll_tokenize(chunk_iter, allow_comments):
    """Tokenizes data from an input stream."""
    alloc_funcs = ffi.new('yajl_alloc_funcs *')
    lib.yajl_set_default_alloc_funcs(alloc_funcs)

    lexer = ffi.gc(
        lib.yajl_lex_alloc(alloc_funcs, allow_comments, False),
        lib.yajl_lex_free,
    )
    decode_buffer = ffi.gc(
        lib.yajl_buf_alloc(alloc_funcs),
        lib.yajl_buf_free,
    )

    out_buffer = ffi.new('unsigned char **')
    out_len = ffi.new('size_t *')

    for chunk in chunk_iter:
        chunk_p = ffi.new('char[]', chunk)
        chunk_len = len(chunk)
        offset = ffi.new('size_t *', 0)

        while True:
            tok = lib.yajl_lex_lex(lexer, chunk_p, chunk_len,
                                   offset,
                                   out_buffer,
                                   out_len)

            if tok == yajl_tok_eof:
                break
            elif tok == yajl_tok_error:
                raise ValueError('Invalid JSON')
            elif tok == yajl_tok_comment:
                continue
            elif tok == yajl_tok_string_with_escapes:
                lib.yajl_string_decode(decode_buffer,
                                       out_buffer[0], out_len[0])
                value = ffi.string(lib.yajl_buf_data(decode_buffer),
                                   lib.yajl_buf_len(decode_buffer))
                lib.yajl_buf_clear(decode_buffer)
                tok = yajl_tok_string
            elif tok in tokens_want_value:
                value = ffi.string(out_buffer[0], out_len[0])
            else:
                value = None
            yield tok, value


def tokenize(f, allow_comments=False, buffer_size=8 * 4096):
    """Tokenizes JSON from a given file stream.  It will consume up to
    `buffer_size` bytes at the time but it will not read past
    newlines.

    This always assumes UTF-8 encoding.
    """
    def _iter_chunks():
        while 1:
            line = f.readline(buffer_size)
            if not line:
                break
            yield line
        # We need to yield some extra whitespace to resolve the
        # case where a number would otherwise not be delimited.  This
        # solves a problem with the lexer being unsure if the number is
        # terminated or not.
        yield ' '

    def _build(token, value):
        if token == yajl_tok_left_brace:
            yield 'start_map', None
            first = True
            while 1:
                token, value = tokeniter.next()
                if token == yajl_tok_right_brace:
                    break
                if not first:
                    if token != yajl_tok_comma:
                        raise ValueError('Missing comma')
                    token, value = tokeniter.next()
                first = False
                for event in _build(token, value):
                    yield event
                token, _ = tokeniter.next()
                if token != yajl_tok_colon:
                    raise ValueError('Missing colon')
                for event in _build(*tokeniter.next()):
                    yield event
            yield 'end_map', None
        elif token == yajl_tok_left_bracket:
            yield 'start_array', None
            first = True
            while 1:
                token, value = tokeniter.next()
                if token == yajl_tok_right_bracket:
                    break
                if not first:
                    if token != yajl_tok_comma:
                        raise ValueError('Missing comma')
                    token, value = tokeniter.next()
                first = False
                for event in _build(token, value):
                    yield event
            yield 'end_array', None
        else:
            conv = token_value_converters.get(token)
            if conv is None:
                raise ValueError('Invalid JSON')
            yield 'value', conv(value)

    tokeniter = _ll_tokenize(_iter_chunks(), allow_comments)
    try:
        first = tokeniter.next()
    except StopIteration:
        return iter(())
    return _build(*first)


def tokenize_string(string, allow_comments=False):
    """Tokenizes a given unicode or literal string."""
    if isinstance(string, unicode):
        string = string.encode('utf-8')
    f = BytesIO(string)
    return tokenize(f, allow_comments)
