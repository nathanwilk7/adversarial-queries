SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_keyword CROSS JOIN aka_title) CROSS JOIN movie_link) CROSS JOIN movie_info_idx) CROSS JOIN link_type) CROSS JOIN movie_info) CROSS JOIN title
WHERE aka_title.production_year = 2009
  AND aka_title.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
