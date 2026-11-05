#include <cstdio>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/ui/immediate_drawer.h>
#include <rex/ui/ui_drawer.h>
#include <rex/ui/vulkan/provider.h>
#include <rex/ui/window.h>
#include <rex/ui/windowed_app.h>

REXCVAR_DEFINE_INT32(smoke_frames, 0, "Rendering test",
                     "Exit after this many frames (0 keeps the window open)");

class RenderSmoke final : public rex::ui::WindowedApp,
                          public rex::ui::UIDrawer,
                          public rex::ui::WindowListener {
public:
  explicit RenderSmoke(rex::ui::WindowedAppContext &context)
      : WindowedApp(context, "d3-render-smoke") {}
  static std::unique_ptr<rex::ui::WindowedApp>
  Create(rex::ui::WindowedAppContext &context) {
    return std::make_unique<RenderSmoke>(context);
  }
  bool OnInitialize() override {
    rex::LogConfig logging;
    logging.log_to_console = true;
    logging.default_level = spdlog::level::warn;
    rex::InitLogging(logging);
    provider_ = rex::ui::vulkan::VulkanProvider::Create(true, true);
    if (!provider_)
      return false;
    presenter_ = provider_->CreatePresenter();
    drawer_ = provider_->CreateImmediateDrawer();
    if (!presenter_ || !drawer_)
      return false;
    drawer_->SetPresenter(presenter_.get());
    uint8_t pixels[4 * 4 * 4];
    for (unsigned y = 0; y < 4; ++y)
      for (unsigned x = 0; x < 4; ++x) {
        auto *pixel = pixels + 4 * (y * 4 + x);
        const bool bright = (x + y) % 2 == 0;
        pixel[0] = bright ? 240 : 35;
        pixel[1] = bright ? 180 : 45;
        pixel[2] = bright ? 55 : 65;
        pixel[3] = 255;
      }
    texture_ = drawer_->CreateTexture(
        4, 4, rex::ui::ImmediateTextureFilter::kNearest, false, pixels);
    if (!texture_)
      return false;
    presenter_->AddUIDrawerFromUIThread(this, 0);
    registered_ = true;
    window_ = rex::ui::Window::Create(app_context(), GetName(), 1000, 600);
    if (!window_)
      return false;
    window_->SetTitle("Diablo III recomp - Vulkan triangle and texture test");
    window_->AddListener(this);
    window_->Open();
    window_->SetPresenter(presenter_.get());
    presenter_->RequestUIPaintFromUIThread();
    return true;
  }
  void Draw(rex::ui::UIDrawContext &context) override {
    using rex::ui::ImmediateVertex;
    const ImmediateVertex vertices[] = {
        {0, 0, 0, 0, 0xff21150f},      {1000, 0, 0, 0, 0xff21150f},
        {1000, 600, 0, 0, 0xff21150f}, {0, 0, 0, 0, 0xff21150f},
        {1000, 600, 0, 0, 0xff21150f}, {0, 600, 0, 0, 0xff21150f},
        {270, 90, 0, 0, 0xff5060ff},   {70, 510, 0, 0, 0xff70e050},
        {470, 510, 0, 0, 0xffff9050},  {570, 160, 0, 0, 0xffffffff},
        {930, 160, 1, 0, 0xffffffff},  {930, 520, 1, 1, 0xffffffff},
        {570, 160, 0, 0, 0xffffffff},  {930, 520, 1, 1, 0xffffffff},
        {570, 520, 0, 1, 0xffffffff}};
    drawer_->Begin(context, 1000, 600);
    rex::ui::ImmediateDrawBatch batch;
    batch.vertices = vertices;
    batch.vertex_count = 15;
    drawer_->BeginDrawBatch(batch);
    rex::ui::ImmediateDraw draw;
    draw.count = 6;
    drawer_->Draw(draw);
    draw.base_vertex = 6;
    draw.count = 3;
    drawer_->Draw(draw);
    draw.base_vertex = 9;
    draw.count = 6;
    draw.texture = texture_.get();
    drawer_->Draw(draw);
    drawer_->EndDrawBatch();
    drawer_->End();
    ++frames_;
    const int limit = REXCVAR_GET(smoke_frames);
    if (limit > 0 && frames_ >= unsigned(limit)) {
      std::printf("Rendered %u Vulkan triangle/texture frames.\n", frames_);
      app_context().RequestDeferredQuit();
    } else if (limit > 0) {
      presenter_->RequestUIPaintFromUIThread();
    }
  }
  void OnClosing(rex::ui::UIEvent &) override {
    app_context().RequestDeferredQuit();
  }

protected:
  void OnDestroy() override {
    if (registered_)
      presenter_->RemoveUIDrawerFromUIThread(this);
    if (window_) {
      window_->RemoveListener(this);
      window_->SetPresenter(nullptr);
      window_.reset();
    }
    texture_.reset();
    if (drawer_)
      drawer_->SetPresenter(nullptr);
    drawer_.reset();
    presenter_.reset();
    provider_.reset();
    rex::ShutdownLogging();
  }

private:
  std::unique_ptr<rex::ui::vulkan::VulkanProvider> provider_;
  std::unique_ptr<rex::ui::Presenter> presenter_;
  std::unique_ptr<rex::ui::ImmediateDrawer> drawer_;
  std::unique_ptr<rex::ui::ImmediateTexture> texture_;
  std::unique_ptr<rex::ui::Window> window_;
  unsigned frames_ = 0;
  bool registered_ = false;
};
REX_DEFINE_APP(d3_render_smoke, RenderSmoke::Create)
