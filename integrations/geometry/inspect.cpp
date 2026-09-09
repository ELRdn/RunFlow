#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_self_intersections.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_triangle_primitive_3.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/Side_of_triangle_mesh.h>
#include "mesh_binary.h"
#include <iostream>
#include <thread>
#include <atomic>
#include <iomanip>
using K=CGAL::Exact_predicates_inexact_constructions_kernel;
using Point=K::Point_3;
using Tri=K::Triangle_3;
using Primitive=CGAL::AABB_triangle_primitive_3<K,std::vector<Tri>::iterator>;
using Tree=CGAL::AABB_tree<CGAL::AABB_traits_3<K,Primitive>>;
int main(int argc,char**argv) {try {
 if(argc<4) throw std::runtime_error("inspect intersect mesh output-prefix | nearest mesh query.bin out.bin");
 auto m=read_mesh(argv[2]); std::vector<Point> p; p.reserve(m.vertices.size());
 for(auto&v:m.vertices)p.emplace_back(v[0],v[1],v[2]);
 std::string action=argv[1],prefix=argv[3];
 if(action=="intersect") {
  std::vector<std::pair<std::size_t,std::size_t>> pairs;
  CGAL::Polygon_mesh_processing::triangle_soup_self_intersections(p,m.faces,std::back_inserter(pairs));
  std::ofstream bin(prefix+".pairs.bin",std::ios::binary);uint64_t deg=0;
  for(auto pair:pairs){uint64_t a=pair.first,b=pair.second;bin.write((char*)&a,8);bin.write((char*)&b,8);deg+=a==b;}
  if(!bin)throw std::runtime_error("pairs write failed");
  std::ofstream j(prefix+".json");j<<"{\"complete\":true,\"kernel\":\"EPICK exact predicates\",\"triangles\":"<<m.faces.size()<<",\"intersection_pairs\":"<<pairs.size()-deg<<",\"degenerate_triangles\":"<<deg<<",\"intersection_free\":"<<(pairs.empty()?"true":"false")<<"}";
  std::cout<<"EXACT_INTERSECTIONS "<<pairs.size()-deg<<" DEGENERATES "<<deg<<std::endl;
 } else if(action=="topology") {
  bool valid=CGAL::Polygon_mesh_processing::is_polygon_soup_a_polygon_mesh(m.faces);
  std::vector<uint64_t> edges;edges.reserve(m.faces.size()*3);
  for(auto&f:m.faces)for(int i=0;i<3;++i){uint64_t a=f[i],b=f[(i+1)%3];edges.push_back((std::min(a,b)<<32)|std::max(a,b));}
  std::sort(edges.begin(),edges.end());size_t boundary=0,nonmanifold=0;
  for(size_t i=0;i<edges.size();){size_t j=i+1;while(j<edges.size()&&edges[j]==edges[i])++j;boundary+=j-i==1;nonmanifold+=j-i>2;i=j;}
  std::ofstream j(prefix);j<<"{\"complete\":true,\"vertex_fans_and_orientation_valid\":"<<(valid?"true":"false")<<",\"boundary_edges\":"<<boundary<<",\"nonmanifold_edges\":"<<nonmanifold<<",\"closed_manifold\":"<<(valid&&!boundary&&!nonmanifold?"true":"false")<<"}";
 } else if(action=="inside") {
  if(argc!=5)throw std::runtime_error("inside needs mesh, query.bin, output.bin");
  if(!CGAL::Polygon_mesh_processing::is_polygon_soup_a_polygon_mesh(m.faces))throw std::runtime_error("Not a manifold surface");
  CGAL::Surface_mesh<Point> sm;CGAL::Polygon_mesh_processing::polygon_soup_to_polygon_mesh(p,m.faces,sm);
  if(!CGAL::is_closed(sm))throw std::runtime_error("Inside classification requires closed surface");
  CGAL::Side_of_triangle_mesh<decltype(sm),K> side(sm);
  std::ifstream q(argv[3],std::ios::binary|std::ios::ate);auto bytes=q.tellg();if(bytes<0||bytes%24)throw std::runtime_error("Invalid point queries");q.seekg(0);
  std::ofstream out(argv[4],std::ios::binary);std::array<double,3> a;
  for(size_t i=0;i<size_t(bytes)/24;++i){q.read((char*)a.data(),24);int8_t value=int8_t(side(Point(a[0],a[1],a[2])));out.write((char*)&value,1);}
  if(!q||!out)throw std::runtime_error("Inside IO failed");
 } else if(action=="cutter") {
  if(argc!=5)throw std::runtime_error("cutter needs cutter mesh, original mesh, result JSON");
  if(!CGAL::Polygon_mesh_processing::is_polygon_soup_a_polygon_mesh(m.faces))throw std::runtime_error("Cutter is not manifold");
  CGAL::Surface_mesh<Point> sm;CGAL::Polygon_mesh_processing::polygon_soup_to_polygon_mesh(p,m.faces,sm);
  if(!CGAL::is_closed(sm))throw std::runtime_error("Cutter not closed");
  std::vector<std::pair<size_t,size_t>> pairs;
  CGAL::Polygon_mesh_processing::triangle_soup_self_intersections(p,m.faces,std::back_inserter(pairs));
  if(!pairs.empty())throw std::runtime_error("Cutter has intersections or degenerates");
  std::vector<Tri> tris;tris.reserve(m.faces.size());for(auto&f:m.faces)tris.emplace_back(p[f[0]],p[f[1]],p[f[2]]);
  Tree tree(tris.begin(),tris.end());CGAL::Side_of_triangle_mesh<decltype(sm),K> side(sm);
  auto source=read_mesh(argv[3]);uint64_t crossing=0,inside=0,on=0;
  for(auto&v:source.vertices){auto s=side(Point(v[0],v[1],v[2]));inside+=s==CGAL::ON_BOUNDED_SIDE;on+=s==CGAL::ON_BOUNDARY;}
  for(auto&f:source.faces){auto&a=source.vertices[f[0]];auto&b=source.vertices[f[1]];auto&c=source.vertices[f[2]];
    Tri t(Point(a[0],a[1],a[2]),Point(b[0],b[1],b[2]),Point(c[0],c[1],c[2]));
    if(t.is_degenerate()) {crossing+=tree.do_intersect(K::Segment_3(t.vertex(0),t.vertex(1)))||tree.do_intersect(K::Segment_3(t.vertex(1),t.vertex(2)));}
    else crossing+=tree.do_intersect(t);
  }
  std::ofstream j(argv[4]);j<<"{\"complete\":true,\"source_triangle_boundary_intersections\":"<<crossing<<",\"source_vertices_inside\":"<<inside<<",\"source_vertices_on_boundary\":"<<on<<",\"source_surface_untouched\":"<<(!crossing&&!inside&&!on?"true":"false")<<"}";
  std::cout<<"CUTTER_CERTIFICATE "<<crossing<<" "<<inside<<" "<<on<<std::endl;
 } else if(action=="nearest") {
  if(argc!=5)throw std::runtime_error("nearest needs query/output");
  std::vector<Tri> tris; tris.reserve(m.faces.size());std::vector<size_t> original_ids;
  struct Degenerate {Point a,b;size_t face;};std::vector<Degenerate> degenerate;
  for(size_t i=0;i<m.faces.size();++i){auto&f=m.faces[i];Tri t(p[f[0]],p[f[1]],p[f[2]]);
   if(t.is_degenerate()) {
    int longest=0;double best=-1;for(int k=0;k<3;++k){double d=CGAL::to_double(CGAL::squared_distance(t.vertex(k),t.vertex((k+1)%3)));if(d>best){best=d;longest=k;}}
    degenerate.push_back({t.vertex(longest),t.vertex((longest+1)%3),i});
   }else{tris.push_back(t);original_ids.push_back(i);}}
  Tree tree(tris.begin(),tris.end());if(!tris.empty())tree.accelerate_distance_queries();
  std::ifstream q(argv[3],std::ios::binary|std::ios::ate);auto bytes=q.tellg();if(bytes<0 || bytes%24)throw std::runtime_error("invalid queries");q.seekg(0);
  std::ofstream out(argv[4],std::ios::binary);const std::size_t count=std::size_t(bytes)/24,chunk=65536;
  for(std::size_t start=0;start<count;start+=chunk){auto n=std::min(chunk,count-start);std::vector<std::array<double,3>> ps(n);std::vector<std::array<double,5>> ds(n);q.read((char*)ps.data(),n*24);
   std::atomic<std::size_t> cursor{0};std::vector<std::thread> threads;
   for(unsigned th=0;th<std::min(24u,std::max(1u,std::thread::hardware_concurrency()));++th)threads.emplace_back([&](){for(;;){auto i=cursor.fetch_add(32);if(i>=n)break;for(auto j=i;j<std::min(i+32,n);++j){auto&a=ps[j];Point qp(a[0],a[1],a[2]),b;size_t face=0;double best=std::numeric_limits<double>::infinity();
    if(!tris.empty()){auto hit=tree.closest_point_and_primitive(qp);b=hit.first;face=original_ids[hit.second-tris.begin()];best=CGAL::to_double(CGAL::squared_distance(qp,b));}
    for(auto&d:degenerate){auto ab=d.b-d.a;double length=CGAL::to_double(ab.squared_length());double u=length?std::clamp(CGAL::to_double((qp-d.a)*ab)/length,0.,1.):0.;Point cp=d.a+ab*u;double sq=CGAL::to_double(CGAL::squared_distance(qp,cp));if(sq<best){best=sq;b=cp;face=d.face;}}
    ds[j]={std::sqrt(best),CGAL::to_double(b.x()),CGAL::to_double(b.y()),CGAL::to_double(b.z()),double(face)};}}});
   for(auto&t:threads)t.join();out.write((char*)ds.data(),n*40);
  }
  if(!q || !out)throw std::runtime_error("nearest IO failed");std::cout<<"NEAREST_COMPLETE "<<count<<std::endl;
 } else throw std::runtime_error("unknown operation");
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}}
