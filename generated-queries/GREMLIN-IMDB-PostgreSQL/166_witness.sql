SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((title CROSS JOIN movie_link) CROSS JOIN aka_title) CROSS JOIN kind_type) CROSS JOIN link_type) CROSS JOIN movie_info) CROSS JOIN movie_info_idx) CROSS JOIN movie_keyword
WHERE kind_type.kind = 'tv series'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
