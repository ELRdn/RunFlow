// Diagnostic companion: same Foundation14 findSelfIntersectOp as surfaceCheck.
// Does not modify the surface or replace the production checker.
#include "triSurface.H"
#include "triSurfaceSearch.H"
#include "treeDataTriSurface.H"
#include "indexedOctree.H"
#include <fstream>
#include <iomanip>
#include <cstdint>
#include <stdexcept>

int main(int argc,char** argv)
{
    if(argc!=3) return 2;
    Foam::triSurface surf{Foam::fileName(argv[1])};
    const std::string prefix=argv[2];
    static_assert(sizeof(Foam::scalar)==8,"Double precision required");
    std::ofstream mesh(prefix+".rfmesh",std::ios::binary);
    const uint64_t nv=surf.points().size(),nf=surf.size();
    mesh.write("RFMESH1\0",8);mesh.write((const char*)&nv,8);mesh.write((const char*)&nf,8);
    for(const auto& p:surf.points()) for(int k=0;k<3;++k) {double x=p[k];mesh.write((char*)&x,8);}
    for(const auto& f:surf) for(int k=0;k<3;++k) {uint32_t x=f[k];mesh.write((char*)&x,4);}
    mesh.close();if(!mesh)throw std::runtime_error("Loaded mesh write failed");
    Foam::Info<<"LOADED "<<nv<<" "<<nf<<Foam::endl;
    Foam::triSurfaceSearch querySurf(surf);
    const auto& tree=querySurf.tree();
    std::ofstream hits(prefix+".hits.csv");hits<<std::setprecision(17);
    hits<<"edge,face,a,b,f0,f1,f2,x,y,z\n";
    uint64_t count=0;
    forAll(surf.edges(),edgeI)
    {
        const auto& e=surf.edges()[edgeI];
        const auto a=surf.meshPoints()[e[0]],b=surf.meshPoints()[e[1]];
        const auto hit=tree.findLine(surf.points()[a],surf.points()[b],
            Foam::treeDataTriSurface::findSelfIntersectOp(tree,edgeI));
        if(hit.hit())
        {
            const auto& f=surf[hit.index()];const auto& p=hit.hitPoint();
            hits<<edgeI<<','<<hit.index()<<','<<a<<','<<b<<','<<f[0]<<','<<f[1]<<','<<f[2]
                <<','<<p[0]<<','<<p[1]<<','<<p[2]<<'\n';++count;
        }
    }
    hits.close();if(!hits)throw std::runtime_error("Hit write failed");
    Foam::Info<<"PROBE_COMPLETE "<<count<<Foam::endl;
    return 0;
}
