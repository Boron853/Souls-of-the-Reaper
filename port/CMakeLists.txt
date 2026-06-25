# diablo3 - ReXGlue Recompiled Project

cmake_minimum_required(VERSION 3.25)
project(diablo3 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(generated/rexglue.cmake)

# Sources
set(DIABLO3_SOURCES
    src/main.cpp
    src/kernel_overrides.cpp
)

if(WIN32)
    add_executable(diablo3 WIN32 ${DIABLO3_SOURCES})
else()
    add_executable(diablo3 ${DIABLO3_SOURCES})
endif()

rexglue_setup_target(diablo3)

# When building the SDK from source (REXSDK_DIR -> add_subdirectory), rexglue_configure_target
# adds rex_app.cpp which includes <imgui.h> and <rex/version.h>. In install mode those headers
# live in the SDK's flat include tree; in source mode they are split:
#   - imgui.h       -> exposed by the 'imgui' target (BUILD_INTERFACE)
#   - rex/version.h -> generated in <build>/rexglue-sdk/include, exposed by 'rexcore' PUBLIC
# Pass include dirs only (no object linking -> no duplicate symbols).
foreach(_dep rexcore imgui)
    if(TARGET ${_dep})
        target_include_directories(diablo3 PRIVATE
            $<TARGET_PROPERTY:${_dep},INTERFACE_INCLUDE_DIRECTORIES>)
    endif()
endforeach()
