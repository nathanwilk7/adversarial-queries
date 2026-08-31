SET join_collapse_limit = 1;
SELECT count(*)
FROM (((title CROSS JOIN name) CROSS JOIN cast_info) CROSS JOIN kind_type) CROSS JOIN aka_title
WHERE kind_type.kind = 'movie'
  AND name.name_pcode_nf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND title.kind_id = kind_type.id;
