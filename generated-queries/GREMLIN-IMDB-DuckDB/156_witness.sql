SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((movie_keyword CROSS JOIN (movie_companies CROSS JOIN ((kind_type CROSS JOIN movie_link) CROSS JOIN title))) CROSS JOIN cast_info) CROSS JOIN link_type) CROSS JOIN movie_info
WHERE kind_type.kind = 'tv series'
  AND cast_info.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
