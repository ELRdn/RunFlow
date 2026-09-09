#pragma once
#include <array>
#include <cstdint>
#include <fstream>
#include <vector>
#include <stdexcept>
#include <cstring>
#include <cmath>
struct BinaryMesh {
 std::vector<std::array<double,3>> vertices;
 std::vector<std::array<std::size_t,3>> faces;
};
inline BinaryMesh read_mesh(const std::string& path) {
 std::ifstream in(path,std::ios::binary); if(!in) throw std::runtime_error("input open failed");
 char magic[8]; uint64_t nv=0,nf=0; in.read(magic,8); in.read((char*)&nv,8); in.read((char*)&nf,8);
 if(std::memcmp(magic,"RFMESH1\0",8) || !nv || !nf || nv>40000000 || nf>40000000) throw std::runtime_error("bad mesh header or face limit");
 BinaryMesh m; m.vertices.resize(nv); m.faces.resize(nf);
 in.read((char*)m.vertices.data(),nv*24);
 for(auto& f:m.faces) {std::array<uint32_t,3> s; in.read((char*)s.data(),12); for(int k=0;k<3;++k) {if(s[k]>=nv) throw std::runtime_error("index out of range");f[k]=s[k];}}
 if(!in || in.peek()!=EOF) throw std::runtime_error("truncated or trailing mesh data");
 for(auto& p:m.vertices) for(auto x:p) if(!std::isfinite(x)) throw std::runtime_error("nonfinite position");
 return m;
}
template<class Points,class Faces>
void write_mesh(const std::string& path,const Points& points,const Faces& faces) {
 std::ofstream out(path,std::ios::binary); if(!out) throw std::runtime_error("output open failed");
 uint64_t nv=points.size(),nf=faces.size();out.write("RFMESH1\0",8);out.write((char*)&nv,8);out.write((char*)&nf,8);
 for(auto& p:points) {std::array<double,3> v{CGAL::to_double(p.x()),CGAL::to_double(p.y()),CGAL::to_double(p.z())};out.write((char*)v.data(),24);}
 for(auto& f:faces) {std::array<uint32_t,3> a{uint32_t(f[0]),uint32_t(f[1]),uint32_t(f[2])};out.write((char*)a.data(),12);}
 if(!out) throw std::runtime_error("output write failed");
}
