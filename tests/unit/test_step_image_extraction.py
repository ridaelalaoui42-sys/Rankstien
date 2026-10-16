from bs4 import BeautifulSoup

from backend.services.news_scraper import _extract_step_images


def extract(html):
    return _extract_step_images(BeautifulSoup(html, "html.parser"), "https://cocina.example/recetas/arroz")


def test_ordinary_figures_follow_preparation_order_and_preserve_captions():
    images = extract("""
        <meta property="og:image" content="/photos/arroz-1200x800.jpg">
        <article>
          <figure class="featured-image"><img src="/photos/arroz.jpg"></figure>
          <h2>Ingredientes</h2><img src="/photos/ingredientes.jpg">
          <h2>Cómo preparar el arroz paso a paso</h2>
          <h3>Paso 1: Sofrito</h3>
          <figure><img src="/photos/cebolla.jpg" alt="Cebolla">
            <figcaption>Sofreír la cebolla hasta que esté transparente.</figcaption>
          </figure>
          <h3>Añadir el arroz</h3>
          <figure><img src="/photos/mezcla.jpg" alt="Mezclar el arroz con el sofrito"></figure>
          <h2>Conservación</h2><img src="/photos/nevera.jpg">
        </article>
    """)
    assert [image["image_url"] for image in images] == [
        "https://cocina.example/photos/cebolla.jpg",
        "https://cocina.example/photos/mezcla.jpg",
    ]
    assert [image["step_number"] for image in images] == [1, 2]
    assert images[0]["text"] == "Sofreír la cebolla hasta que esté transparente."
    assert images[1]["text"] == "Mezclar el arroz con el sofrito"


def test_lazy_images_replace_data_uri_and_http_placeholders():
    images = extract("""
        <div class="entry-content"><h2>Elaboración</h2>
          <figure><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="
            data-src="../photos/cortar.jpg" alt="Cortar las verduras"></figure>
          <img src="/images/placeholder.gif" data-lazy-src="//cdn.example/sofreir.jpg">
          <img src="/images/loading.gif" data-original="/photos/arroz.jpg">
        </div>
    """)
    assert [image["image_url"] for image in images] == [
        "https://cocina.example/photos/cortar.jpg",
        "https://cdn.example/sofreir.jpg",
        "https://cocina.example/photos/arroz.jpg",
    ]


def test_responsive_images_choose_largest_candidate_and_deduplicate_variants():
    images = extract("""
        <article><h2>Preparación</h2>
          <figure><img src="/photos/mezclar-300x200.jpg"
            data-srcset="/photos/mezclar-600x400.jpg 600w, /photos/mezclar-1200x800.jpg 1200w">
          </figure>
          <noscript><img src="/photos/mezclar.jpg"></noscript>
          <picture><source srcset="//cdn.example/cocer-small.webp 1x, //cdn.example/cocer.webp 2x">
            <img src="/photos/cocer-small.jpg" alt="Cocer a fuego lento">
          </picture>
          <img src="/photos/reposar-small.jpg" srcset="/photos/reposar-small.jpg 400w, /photos/reposar.jpg 900w">
        </article>
    """)
    assert [image["image_url"] for image in images] == [
        "https://cocina.example/photos/mezclar-1200x800.jpg",
        "https://cdn.example/cocer.webp",
        "https://cocina.example/photos/reposar.jpg",
    ]


def test_generic_content_keeps_first_unknown_photo_and_excludes_known_hero_and_noise():
    images = extract("""
        <meta property="og:image" content="/photos/arroz.jpg">
        <div class="entry-content">
          <figure><img src="/photos/cortar.jpg"><figcaption>Picar la cebolla.</figcaption></figure>
          <img src="/photos/arroz-900x600.jpg">
          <img src="/photos/mezclar.jpg" alt="Mezclar los ingredientes">
          <img src="/assets/logo.png"><img src="/assets/avatar.jpg"><img src="/assets/spacer.gif">
          <img src="/photos/tiny.jpg" width="24" height="24">
          <aside><img src="/photos/other.jpg"></aside>
          <div class="publicidad"><img src="/photos/promocion.jpg"></div>
          <div class="related-recipes"><img src="/photos/otra-receta.jpg"></div>
          <div class="author-bio"><img src="/photos/chef.jpg"></div>
          <h2>Otras recetas que te pueden gustar</h2><img src="/photos/pollo.jpg">
        </div>
        <footer><img src="/photos/footer.jpg"></footer>
    """)
    assert [image["image_url"] for image in images] == [
        "https://cocina.example/photos/cortar.jpg",
        "https://cocina.example/photos/mezclar.jpg",
    ]


def test_srcset_preserves_commas_inside_cdn_transform_urls():
    images = extract("""
        <article><h2>Preparación</h2>
          <img data-srcset="https://cdn.example/image/upload/c_scale,w_1200/sofrito.jpg 1200w,
            https://cdn.example/image/upload/c_scale,w_600/sofrito.jpg 600w">
        </article>
    """)
    assert [image["image_url"] for image in images] == [
        "https://cdn.example/image/upload/c_scale,w_1200/sofrito.jpg"
    ]


def test_single_image_instruction_container_is_supported():
    images = extract("""
        <div class="instrucciones"><p>Mezclar el arroz cocido con las verduras.</p>
          <figure><img data-src="/photos/mezclar.jpg"></figure>
        </div>
    """)
    assert images == [
        {
            "step_number": 1,
            "image_url": "https://cocina.example/photos/mezclar.jpg",
            "text": "Mezclar el arroz cocido con las verduras.",
        }
    ]


def test_instruction_lists_keep_each_photos_own_step_text():
    images = extract("""
        <ol class="recipe-instructions">
          <li>Picar la cebolla.<img data-src="/photos/picar.jpg"></li>
          <li>Sofreír la cebolla.<img data-src="/photos/sofreir.jpg"></li>
        </ol>
    """)
    assert [image["text"] for image in images] == ["Picar la cebolla.", "Sofreír la cebolla."]
    assert [image["step_number"] for image in images] == [1, 2]


def test_numbered_images_keep_order_with_lazy_urls_and_caption_numbers():
    images = extract("""
        <div class="entry-content">
          <img src="/placeholder.gif" data-lazy-src="/photos/arroz-paso-2.jpg" alt="Cocer">
          <figure><img data-srcset="/photos/sofrito.jpg 800w">
            <figcaption>Paso 1: Preparar el sofrito</figcaption></figure>
        </div>
    """)
    assert [image["step_number"] for image in images] == [1, 2]
    assert images[0]["image_url"] == "https://cocina.example/photos/sofrito.jpg"
    assert images[1]["image_url"] == "https://cocina.example/photos/arroz-paso-2.jpg"


def test_nested_schema_steps_resolve_relative_images_and_merge_missing_dom_photos():
    images = extract("""
        <script type="application/ld+json">
          {"@graph": [{"@type": ["Recipe", "HowTo"], "image": "/photos/hero.jpg",
            "recipeInstructions": [{"@type": "HowToSection", "itemListElement": [
              {"@type": "HowToStep", "text": "Picar las verduras."},
              {"@type": "HowToStep", "text": "Dorar las verduras.",
                "image": [{"@type": "ImageObject", "contentUrl": "/photos/dorar.jpg"}]}]}]}]}
        </script>
        <article><h2>Preparación</h2>
          <img src="/photos/hero-600x400.jpg">
          <figure><img src="/photos/picar.jpg" alt="Picar las verduras"></figure>
          <figure><img src="/photos/dorar-1200x800.jpg" alt="Dorar"></figure>
          <figure><img src="/photos/cocer.jpg" alt="Cocer a fuego lento"></figure>
        </article>
    """)
    assert [image["step_number"] for image in images] == [1, 2, 3]
    assert [image["image_url"] for image in images] == [
        "https://cocina.example/photos/picar.jpg",
        "https://cocina.example/photos/dorar.jpg",
        "https://cocina.example/photos/cocer.jpg",
    ]
    assert images[1]["text"] == "Dorar las verduras."


def test_unscoped_images_are_not_treated_as_preparation_photos():
    assert extract('<div><figure><img src="/photos/unknown.jpg"></figure></div>') == []


def test_schema_step_wins_over_alternate_numbered_photo_without_readding_it():
    images = extract("""
        <script type="application/ld+json">
          {"@type": "Recipe", "recipeInstructions": [
            {"@type": "HowToStep", "text": "Dorar la cebolla.", "image": "/photos/schema-first.jpg"}]}
        </script>
        <article><h2>Preparación</h2>
          <img src="/photos/arroz-paso-1.jpg" alt="Paso 1: Dorar la cebolla">
          <img src="/photos/alternativa-paso-1.jpg" alt="Paso 1: Dorar de nuevo">
          <img src="/photos/cocer.jpg" alt="Cocer el arroz">
        </article>
    """)
    assert images == [
        {
            "step_number": 1,
            "image_url": "https://cocina.example/photos/schema-first.jpg",
            "text": "Dorar la cebolla.",
        },
        {
            "step_number": 2,
            "image_url": "https://cocina.example/photos/cocer.jpg",
            "text": "Cocer el arroz",
        },
    ]


def test_malformed_schema_and_image_urls_do_not_hide_valid_photos():
    images = extract("""
        <script type="application/ld+json">{bad json</script>
        <article><h2>Preparación</h2>
          <img src="https://[invalid/foo.jpg">
          <img src="data:image/gif;base64,AAA" srcset="data:image/gif;base64,AAA 1x">
          <img src="/photos/cocer.jpg">
        </article>
    """)
    assert [image["image_url"] for image in images] == ["https://cocina.example/photos/cocer.jpg"]
