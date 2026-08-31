SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((movie_info_idx CROSS JOIN kind_type) CROSS JOIN (title CROSS JOIN movie_keyword)) CROSS JOIN movie_info) CROSS JOIN movie_link) CROSS JOIN keyword
WHERE kind_type.kind = 'tv series'
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
