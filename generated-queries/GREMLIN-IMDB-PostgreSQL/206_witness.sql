SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_link CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN kind_type) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN keyword) CROSS JOIN role_type
WHERE name.name_pcode_nf = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
