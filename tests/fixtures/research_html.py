"""Fixtures de HTML público de YouTube para tests offline.

HTML mínimo pero realista: YouTube embebe `var ytInitialData = {...};` y
`var ytInitialPlayerResponse = {...};` en las páginas públicas. Estos
fixtures reproducen esa estructura para probar los parsers sin red.
"""

CHANNEL_HTML = """<!DOCTYPE html>
<html><head><title>Canal</title></head><body>
<script>var ytInitialData = {
  "header": {
    "c4TabbedHeaderRenderer": {
      "title": {"simpleText": "Canal Demo"},
      "subscriberCountText": {"simpleText": "12,3 K suscriptores"},
      "channelHandleText": {"runs": [{"text": "@canaldemo"}]},
      "navigationEndpoint": {"canonicalBaseUrl": "/@canaldemo"}
    }
  },
  "contents": {
    "twoColumnBrowseResultsRenderer": {
      "tabs": [
        {"tabRenderer": {"title": "Videos", "content": {
          "richGridRenderer": {
            "contents": [
              {"richItemRenderer": {"content": {
                "videoRenderer": {
                  "videoId": "abc123def45",
                  "title": {"runs": [{"text": "Vídeo de prueba #1"}]},
                  "viewCountText": {"simpleText": "1.234 visualizaciones"},
                  "lengthText": {"simpleText": "12:34"},
                  "publishedTimeText": {"simpleText": "hace 2 semanas"},
                  "thumbnail": {"thumbnails": [{"url": "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg"}]}
                }
              }}}
            ]
          }
        }}}
      ]
    }
  }
};</script>
</body></html>
"""

# Formato nuevo (sept. 2026): la pestaña de vídeos usa ``lockupViewModel``
# dentro de ``richGridRenderer`` → ``richItemRenderer`` → ``content``.
CHANNEL_HTML_LOCKUP = """<!DOCTYPE html>
<html><head><title>Canal</title></head><body>
<script>var ytInitialData = {
  "header": {
    "c4TabbedHeaderRenderer": {
      "title": {"simpleText": "Canal Demo"},
      "subscriberCountText": {"simpleText": "12,3 K suscriptores"},
      "channelHandleText": {"runs": [{"text": "@canaldemo"}]},
      "navigationEndpoint": {"canonicalBaseUrl": "/@canaldemo"}
    }
  },
  "contents": {
    "twoColumnBrowseResultsRenderer": {
      "tabs": [
        {"tabRenderer": {"title": "Videos", "content": {
          "richGridRenderer": {
            "contents": [
              {"richItemRenderer": {"content": {
                "lockupViewModel": {
                  "contentId": "lockup12345",
                  "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                  "contentImage": {
                    "thumbnailViewModel": {
                      "image": {"sources": [{"url": "https://i.ytimg.com/vi/lockup12345/hqdefault.jpg"}]},
                      "overlays": [{"thumbnailBottomOverlayViewModel": {
                        "badges": [{"thumbnailBadgeViewModel": {"text": "12:34"}}]
                      }}]
                    }
                  },
                  "metadata": {"lockupMetadataViewModel": {
                    "title": {"content": "Vídeo lockup #1"},
                    "metadata": {"contentMetadataViewModel": {
                      "metadataRows": [{"metadataParts": [
                        {"text": {"content": "84 M de visualizaciones"}},
                        {"text": {"content": "hace 3 días"}}
                      ]}]
                    }}
                  }}
                }
              }}}
            ]
          }
        }}}
      ]
    }
  }
};</script>
</body></html>
"""

VIDEO_HTML = """<!DOCTYPE html>
<html><head><title>Vídeo</title></head><body>
<script>var ytInitialPlayerResponse = {
  "videoDetails": {
    "videoId": "abc123def45",
    "title": "Vídeo de prueba #1",
    "lengthSeconds": "754",
    "shortDescription": "Descripción del vídeo #test #youtube #aprendizaje",
    "viewCount": "1234",
    "author": "Canal Demo",
    "channelId": "UCdemo123456789",
    "thumbnail": {"thumbnails": [{"url": "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg"}]}
  },
  "microformat": {
    "playerMicroformatRenderer": {
      "publishDate": "2026-08-15",
      "ownerChannelName": "Canal Demo"
    }
  }
};</script>
<script>var ytInitialData = {
  "contents": {
    "twoColumnWatchNextResults": {
      "results": {
        "results": {
          "contents": [
            {"videoPrimaryInfoRenderer": {
              "videoActions": {
                "menuRenderer": {
                  "topLevelButtons": [
                    {"toggleButtonRenderer": {
                      "defaultText": {"simpleText": "98"}
                    }}
                  ]
                }
              }
            }}
          ]
        }
      }
    }
  },
  "engagementPanels": [
    {"engagementPanelSectionListRenderer": {
      "content": {
        "structuredDescriptionContentRenderer": {
          "items": [
            {"videoDescriptionHeaderRenderer": {}}
          ]
        }
      }
    }}
  ],
  "commentsEntryPointHeaderRenderer": {
    "commentCount": {"simpleText": "12"}
  }
};</script>
</body></html>
"""

# Vídeo sin likes ni comentarios visibles (p. ej. comentarios desactivados).
VIDEO_HTML_NO_SOCIAL = """<!DOCTYPE html>
<html><head><title>Vídeo</title></head><body>
<script>var ytInitialPlayerResponse = {
  "videoDetails": {
    "videoId": "xyz98765432",
    "title": "Vídeo sin métricas sociales",
    "lengthSeconds": "60",
    "shortDescription": "",
    "viewCount": "42",
    "author": "Canal Demo",
    "channelId": "UCdemo123456789",
    "thumbnail": {"thumbnails": []}
  },
  "microformat": {"playerMicroformatRenderer": {"publishDate": "2026-08-01"}}
};</script>
</body></html>
"""
