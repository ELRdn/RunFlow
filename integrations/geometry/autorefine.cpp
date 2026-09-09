#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/autorefinement.h>
#include "mesh_binary.h"
#include <iostream>
using K=CGAL::Exact_predicates_inexact_constructions_kernel;
int main(int argc,char**argv){try{
 if(argc!=5)throw std::runtime_error("autorefine input output snap-grid-exponent iterations");
 auto m=read_mesh(argv[1]);std::vector<K::Point_3> points;
 for(auto&p:m.vertices)points.emplace_back(p[0],p[1],p[2]);
 auto grid=std::stoul(argv[3]),iterations=std::stoul(argv[4]);if(grid<23 || grid>=52 || iterations<1 || iterations>5)throw std::runtime_error("snap parameter limit");
 // CGAL 6.2.1 internally compares this named value with an int literal in std::min.
 bool ok=CGAL::Polygon_mesh_processing::autorefine_triangle_soup(points,m.faces,CGAL::parameters::apply_iterative_snap_rounding(true).snap_grid_size(int(grid)).number_of_iterations(int(iterations)));
 write_mesh(argv[2],points,m.faces);std::cout<<"AUTOREFINE_COMPLETE "<<ok<<" "<<points.size()<<" "<<m.faces.size()<<std::endl;
 return ok?0:3;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}}
