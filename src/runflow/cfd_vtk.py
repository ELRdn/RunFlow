"""Read Foundation foamToVTK legacy cell data, ASCII or big-endian binary."""
from array import array
import math
from pathlib import Path
import sys


TYPES={'float':'f','double':'d','int':'i','unsigned_int':'I'}


def line(stream):
    while True:
        raw=stream.readline()
        if not raw: return []
        words=raw.decode('ascii').split()
        if words: return words


def numbers(stream,count,kind,binary):
    if count<0 or kind not in TYPES: raise ValueError('Unsupported VTK array type/count')
    if binary:
        values=array(TYPES[kind]); size=values.itemsize*count
        raw=stream.read(size)
        if len(raw)!=size: raise ValueError('Truncated binary VTK array')
        values.frombytes(raw)
        if sys.byteorder=='little': values.byteswap()
        return values.tolist()
    values=[]; convert=float if kind in ('float','double') else int
    while len(values)<count:
        words=line(stream)
        if not words: raise ValueError('Truncated ASCII VTK array')
        values.extend(map(convert,words))
    if len(values)!=count: raise ValueError('VTK array length mismatch')
    return values


def read_vtk(path):
    points=[]; cells=[]; fields={}; cell_count=None; cell_types=[]
    with Path(path).open('rb') as stream:
        if not stream.readline().startswith(b'# vtk DataFile Version'):
            raise ValueError('Unsupported VTK header')
        stream.readline()  # free-text title
        mode=line(stream)
        if mode not in (['ASCII'],['BINARY']): raise ValueError('Unsupported VTK encoding')
        binary=mode==['BINARY']
        if line(stream)!=['DATASET','UNSTRUCTURED_GRID']:
            raise ValueError('Expected unstructured cell-data VTK')
        while words:=line(stream):
            tag=words[0]
            if tag=='POINTS':
                n=int(words[1]); values=numbers(stream,3*n,words[2],binary)
                points=[tuple(values[i:i+3]) for i in range(0,len(values),3)]
            elif tag=='CELLS':
                n,size=map(int,words[1:]); values=numbers(stream,size,'int',binary); i=0
                for _ in range(n):
                    if i>=len(values): raise ValueError('Truncated VTK connectivity')
                    length=values[i]; i+=1
                    if length<4 or i+length>len(values): raise ValueError('Invalid VTK cell size')
                    cells.append(values[i:i+length]); i+=length
                if i!=len(values): raise ValueError('VTK connectivity length mismatch')
            elif tag=='CELL_TYPES':
                cell_types=numbers(stream,int(words[1]),'int',binary)
            elif tag=='CELL_DATA': cell_count=int(words[1])
            elif tag=='FIELD':
                for _ in range(int(words[2])):
                    header=line(stream)
                    if len(header)!=4: raise ValueError('Incomplete VTK field header')
                    name,components,count,kind=header; components=int(components); count=int(count)
                    if components<=0: raise ValueError('Invalid VTK component count')
                    values=numbers(stream,components*count,kind,binary)
                    if name in ('p','U') and cell_count is not None:
                        expected=1 if name=='p' else 3
                        if components!=expected or count!=cell_count: raise ValueError('VTK p/U shape mismatch')
                        if not all(math.isfinite(v) for v in values): raise ValueError('Non-finite VTK field')
                        fields[name]=[tuple(values[i:i+components]) for i in range(0,len(values),components)]
            else: raise ValueError('Unsupported VTK section: '+tag)
    if not points or len(cells)!=cell_count or len(cell_types)!=cell_count or not {'p','U'}.issubset(fields):
        raise ValueError('Unsupported/incomplete cell-data VTK: '+Path(path).name)
    if any(kind not in (10,11,12,13,14) for kind in cell_types):
        raise ValueError('Expected decomposed convex VTK volume cells')
    if any(i<0 or i>=len(points) for cell in cells for i in cell):
        raise ValueError('VTK point index out of bounds')
    if not all(math.isfinite(v) for point in points for v in point): raise ValueError('Non-finite VTK point')
    return points,cells,fields
