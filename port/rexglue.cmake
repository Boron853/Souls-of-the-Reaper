# Builds the game against the pinned ReXGlue 0.10 SDK installed by build.ps1 -BuildSdk.
find_package(rexglue 0.10.0 REQUIRED CONFIG)
set(_generated "${CMAKE_CURRENT_SOURCE_DIR}/generated/default")
if(NOT EXISTS "${_generated}/sources.cmake")
    message(FATAL_ERROR "Run build.ps1 (without -SkipCodegen) to generate the game sources first")
endif()
include("${_generated}/sources.cmake")

function(rexglue_setup_target target)
    add_library(${target}_recomp OBJECT ${GENERATED_SOURCES})
    target_include_directories(${target}_recomp PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}/src" "${_generated}")
    target_link_libraries(${target}_recomp PRIVATE rex::runtime)
    rexglue_apply_target_settings(${target}_recomp)
    target_precompile_headers(${target}_recomp PRIVATE "${_generated}/diablo3_pch.h")
    if(WIN32)
        target_compile_options(${target}_recomp PRIVATE -fasync-exceptions)
    else()
        target_compile_options(${target}_recomp PRIVATE -g0)
    endif()
    target_include_directories(${target} PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}/src" "${_generated}")
    target_link_libraries(${target} PRIVATE ${target}_recomp rex::runtime ${CMAKE_DL_LIBS})
    rexglue_configure_target(${target} GPU_PLUGINS xenos)
    # The installed SDK stages plugins but does not stage the runtime DSO.
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:rex::runtime> $<TARGET_FILE_DIR:${target}>)
endfunction()
