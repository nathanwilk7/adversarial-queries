SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((title CROSS JOIN complete_cast) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN movie_keyword) CROSS JOIN aka_title) CROSS JOIN keyword) CROSS JOIN kind_type) CROSS JOIN movie_link
WHERE info_type.info = 'LD production country'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
