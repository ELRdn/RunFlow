#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/repair_polygon_soup.h>
#include <CGAL/Polygon_mesh_processing/orient_polygon_soup_extension.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include "mesh_binary.h"
#include <iostream>
#include <vector>

using K = CGAL::Exact_predicates_inexact_constructions_kernel;
namespace PMP = CGAL::Polygon_mesh_processing;

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("repair_soup input.rfmesh output.rfmesh");
        auto input = read_mesh(argv[1]);
        std::vector<K::Point_3> points;
        points.reserve(input.vertices.size());
        for (const auto& p : input.vertices) points.emplace_back(p[0], p[1], p[2]);
        auto polygons = input.faces;
        const auto before_points = points.size();
        const auto before_polygons = polygons.size();
        PMP::repair_polygon_soup(points, polygons);
        const bool before_duplicate_split = PMP::is_polygon_soup_a_polygon_mesh(polygons);
        const bool duplicated = PMP::duplicate_non_manifold_edges_in_polygon_soup(points, polygons);
        const bool after_duplicate_split = PMP::is_polygon_soup_a_polygon_mesh(polygons);
        write_mesh(argv[2], points, polygons);
        std::cout << "REPAIR_SOUP_COMPLETE " << before_points << " " << before_polygons
                  << " " << points.size() << " " << polygons.size() << " "
                  << before_duplicate_split << " " << duplicated << " "
                  << after_duplicate_split << std::endl;
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << std::endl;
        return 2;
    }
}
