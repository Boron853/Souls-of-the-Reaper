# d3-patch: applies a title update's XEX delta (Default.xexp) to the base-disc
# executable with XenonRecomp's XenonUtils. scripts/build_client.py clones the
# pinned XenonRecomp revision and passes it as XENONRECOMP_DIR.
cmake_minimum_required(VERSION 3.20)
project(D3Patch LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
# XenonRecomp builds with the static MSVC runtime; match it so the link succeeds.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

if(NOT XENONRECOMP_DIR)
    message(FATAL_ERROR "Set XENONRECOMP_DIR to a XenonRecomp checkout with submodules")
endif()
# Only XenonUtils is needed; the recompiler and analyser stay unbuilt.
add_subdirectory(${XENONRECOMP_DIR} xenonrecomp EXCLUDE_FROM_ALL)

add_executable(d3-patch patch_xex.cpp)
target_link_libraries(d3-patch PRIVATE XenonUtils)
target_include_directories(d3-patch PRIVATE ${XENONRECOMP_DIR}/thirdparty/TinySHA1)

# d3-image: dumps the loaded PPC image for scripts/find_feature_addresses.py.
add_executable(d3-image dump_image.cpp)
target_link_libraries(d3-image PRIVATE XenonUtils)
