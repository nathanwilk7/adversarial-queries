SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((((title CROSS JOIN movie_info) CROSS JOIN keyword) CROSS JOIN kind_type) CROSS JOIN info_type) CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN char_name) CROSS JOIN link_type) CROSS JOIN movie_keyword) CROSS JOIN movie_link) CROSS JOIN name
WHERE char_name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
